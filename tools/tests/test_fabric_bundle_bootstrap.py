"""Unit tests for the bootstrap module every bundle zip ships (fabric_bundle_bootstrap.py).

Exercises the real code path with a hand-made bundle: a zip carrying
deployment.json, a code tree, and a wheels/ folder with one minimal pure-Python
wheel. pip is invoked for real (offline, --no-index), so the install branch is
covered too.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import fabric_bundle_bootstrap as fbb
import pytest

RUNNING_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"


def _minimal_wheel(dest: Path, name: str = "jaffle_probe", version: str = "0.1") -> Path:
    """A valid py3-none-any wheel with one importable module, no build tools needed."""
    dist_info = f"{name}-{version}.dist-info"
    files = {
        f"{name}/__init__.py": f'VERSION = "{version}"\n',
        f"{dist_info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{dist_info}/top_level.txt": f"{name}\n",
    }
    record_lines = []
    for path, text in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=").decode()
        record_lines.append(f"{path},sha256={digest},{len(text.encode())}")
    record_lines.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = "\n".join(record_lines) + "\n"
    wheel = dest / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return wheel


def _bundle(tmp_path: Path, deployment: dict, *, with_wheels: bool = True) -> Path:
    wheels_dir = tmp_path / "src_wheels"
    wheels_dir.mkdir()
    wheel = _minimal_wheel(wheels_dir)
    zip_path = tmp_path / "jaffle_shop_test.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("deployment.json", json.dumps(deployment))
        archive.writestr("models/staging/stg_orders.sql", "select 1")
        if with_wheels:
            archive.write(wheel, f"wheels/{wheel.name}")
            archive.writestr("wheels/requirements.txt", "jaffle-probe==0.1\n")
    return zip_path


def _deployment(**overrides) -> dict:
    base = {
        "project": "jaffle_shop_test",
        "commit": "0123456789abcdef0123",
        "published_utc": "2026-09-03T12:00:00+00:00",
        "runtime_version": "2.0",
        "wheel_python_version": RUNNING_PYTHON,
        "wheel_requirements": ["jaffle-probe==0.1"],
    }
    base.update(overrides)
    return base


def test_bootstrap_extracts_installs_and_is_idempotent(tmp_path, capsys):
    zip_path = _bundle(tmp_path, _deployment())
    scratch = tmp_path / "scratch"

    first = fbb.bootstrap(zip_path, scratch_root=scratch, add_to_sys_path=False)

    assert first.extracted and first.installed
    assert first.bundle_dir == scratch / "jaffle_shop_test" / "0123456789ab"
    assert (first.bundle_dir / "models" / "staging" / "stg_orders.sql").is_file()
    assert (first.bundle_dir / fbb.COMPLETE_MARKER).is_file()
    assert (first.site_dir / "jaffle_probe" / "__init__.py").is_file()
    assert (first.site_dir / fbb.COMPLETE_MARKER).is_file()
    assert "installed" in capsys.readouterr().out

    second = fbb.bootstrap(zip_path, scratch_root=scratch, add_to_sys_path=False)

    assert not second.extracted and not second.installed
    assert second.site_dir == first.site_dir
    assert "reused" in capsys.readouterr().out
    # no partial leftovers either way
    assert not list(scratch.glob("**/*.partial-*"))


def test_bootstrap_puts_site_on_sys_path(tmp_path, monkeypatch):
    zip_path = _bundle(tmp_path, _deployment())
    monkeypatch.setattr(sys, "path", list(sys.path))

    context = fbb.bootstrap(zip_path, scratch_root=tmp_path / "scratch", quiet=True)

    assert sys.path[0] == str(context.site_dir)


def test_evict_shadowed_drops_preloaded_modules_the_bundle_replaces(tmp_path, monkeypatch):
    """The Python-notebook kernel has already imported the runtime's azure-core when
    the bootstrap runs; the bundle's copy must win for dbt's later imports."""
    zip_path = _bundle(tmp_path, _deployment())
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "jaffle_probe", raising=False)

    # a stale copy loaded from somewhere else before the bootstrap
    stale_dir = tmp_path / "runtime_site" / "jaffle_probe"
    stale_dir.mkdir(parents=True)
    (stale_dir / "__init__.py").write_text('VERSION = "runtime-old"\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "runtime_site"))
    import jaffle_probe  # noqa: PLC0415

    assert jaffle_probe.VERSION == "runtime-old"

    context = fbb.bootstrap(zip_path, scratch_root=tmp_path / "scratch", evict_shadowed=True, quiet=True)

    assert "jaffle_probe" not in sys.modules  # evicted
    import jaffle_probe as fresh  # noqa: PLC0415

    assert fresh.VERSION == "0.1"
    assert Path(fresh.__file__).parent.parent == context.site_dir
    # a second pass finds only the bundle's own copy and leaves it alone
    assert fbb.evict_shadowed_modules(context.site_dir) == []
    assert sys.modules["jaffle_probe"] is fresh
    monkeypatch.delitem(sys.modules, "jaffle_probe", raising=False)


def test_pruned_package_drift_compares_the_manifest_with_this_kernel(tmp_path, capsys):
    import pytest as pytest_dist  # noqa: PLC0415 — a distribution certainly installed here

    real = pytest_dist.__version__
    deployment = _deployment(pruned_runtime_packages=[f"pytest=={real}", "pytest==0.0.1", "no-such-dist-xyz==1.0", "malformed"])
    drift = fbb.pruned_package_drift(deployment)
    assert drift == [
        f"pytest: this kernel has {real}, the bundle was resolved against the runtime's 0.0.1",
        "no-such-dist-xyz: not installed in this kernel, but the bundle relies on the runtime's 1.0",
    ]
    # surfaced by bootstrap as warnings, never as a failure
    zip_path = _bundle(tmp_path, deployment)
    fbb.bootstrap(zip_path, scratch_root=tmp_path / "scratch", add_to_sys_path=False)
    out = capsys.readouterr().out
    assert "WARNING: pytest: this kernel has" in out and "refresh tools/runtime_constraints" in out
    assert fbb.pruned_package_drift({}) == []


def test_bundled_top_level_names_reads_dist_info_and_falls_back_to_the_tree(tmp_path):
    site = tmp_path / "site"
    (site / "azure_core-1.41.0.dist-info").mkdir(parents=True)
    (site / "azure_core-1.41.0.dist-info" / "top_level.txt").write_text("azure\n", encoding="utf-8")
    (site / "azure" / "core").mkdir(parents=True)
    (site / "dbt").mkdir()
    (site / "six.py").write_text("", encoding="utf-8")
    (site / "bin").mkdir()
    (site / "_virtualenv.pth").write_text("", encoding="utf-8")
    (site / "__pycache__").mkdir()
    assert fbb.bundled_top_level_names(site) == {"azure", "dbt", "six"}


def test_python_version_mismatch_names_the_fix(tmp_path):
    zip_path = _bundle(tmp_path, _deployment(wheel_python_version="2.7", runtime_version="9.9"))

    with pytest.raises(fbb.BundleBootstrapError) as excinfo:
        fbb.bootstrap(zip_path, scratch_root=tmp_path / "scratch", add_to_sys_path=False)

    message = str(excinfo.value)
    assert "Python 2.7" in message and "runtime '9.9'" in message and RUNNING_PYTHON in message
    assert "--runtime" in message
    assert not (tmp_path / "scratch").exists()  # failed before touching disk


def test_missing_wheels_folder_is_rejected(tmp_path):
    zip_path = _bundle(tmp_path, _deployment(), with_wheels=False)

    with pytest.raises(fbb.BundleBootstrapError, match="wheels/requirements.txt"):
        fbb.bootstrap(zip_path, scratch_root=tmp_path / "scratch", add_to_sys_path=False)


def test_missing_deployment_is_rejected(tmp_path):
    zip_path = tmp_path / "plain.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("wheels/requirements.txt", "")

    with pytest.raises(fbb.BundleBootstrapError, match="deployment.json"):
        fbb.bootstrap(zip_path, scratch_root=tmp_path / "scratch", add_to_sys_path=False)


def test_bundle_key_prefers_commit_then_publish_time():
    assert fbb.bundle_key({"commit": "abcdef0123456789"}) == "abcdef012345"
    assert fbb.bundle_key({"published_utc": "2026-09-03T12:00:00+00:00"}) == "20260903T1200000000"
    assert fbb.bundle_key({}) == "unversioned"


def test_materialize_loser_discards_its_partial(tmp_path):
    target = tmp_path / "site"

    def build_and_get_beaten(partial: Path):
        # a concurrent caller finishes first
        target.mkdir(parents=True)
        (target / fbb.COMPLETE_MARKER).write_text("winner", encoding="utf-8")
        (partial / "mine.txt").write_text("loser", encoding="utf-8")

    assert fbb._materialize(target, build_and_get_beaten) is False
    assert (target / fbb.COMPLETE_MARKER).read_text(encoding="utf-8") == "winner"
    assert not list(tmp_path.glob("*.partial-*"))


def test_materialize_cleans_up_when_build_fails(tmp_path):
    target = tmp_path / "site"

    def explode(partial: Path):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        fbb._materialize(target, explode)
    assert not target.exists()
    assert not list(tmp_path.glob("*.partial-*"))


def test_module_is_zipimportable(tmp_path, monkeypatch):
    """The notebook cell imports this module straight from the zip."""
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(Path(fbb.__file__), "bundle_bootstrap.py")
    monkeypatch.setattr(sys, "path", [str(zip_path), *sys.path])
    monkeypatch.delitem(sys.modules, "bundle_bootstrap", raising=False)

    import bundle_bootstrap  # noqa: PLC0415 — the point of the test

    assert Path(bundle_bootstrap.__file__).parent == zip_path
    assert callable(bundle_bootstrap.bootstrap)
    monkeypatch.delitem(sys.modules, "bundle_bootstrap", raising=False)


def test_stdlib_only():
    """It runs before anything is installed, so it may import only the stdlib."""
    source = Path(fbb.__file__).read_text(encoding="utf-8")
    imports = {
        line.split()[1].split(".")[0]
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and not line.startswith("from __future__")
    }
    assert imports <= set(sys.stdlib_module_names), imports - set(sys.stdlib_module_names)


def test_zip_stream_roundtrip_smoke():
    """Guard the in-memory zip idiom the publisher uses."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("deployment.json", "{}")
    assert zipfile.ZipFile(io.BytesIO(buffer.getvalue())).namelist() == ["deployment.json"]
