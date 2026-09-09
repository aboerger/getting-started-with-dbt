"""Kernel-side bootstrap for the dbt project bundles in the Fabric runner notebooks.

A *bundle* is the zip ``tools/publish_dbt_bundle.py`` uploads to the
lakehouse's ``Files/``: the dbt project tree, a root ``deployment.json`` build
stamp, a ``wheels/`` folder holding exactly the wheels the Fabric runtime does
not already ship, and a copy of this file as ``bundle_bootstrap.py``. The
notebook's bootstrap cell downloads the zip, imports this module *from the zip*
(zipimport), and calls :func:`bootstrap`. The same file serves the PySpark
notebook (``NB_dbt_Runner_Spark``) and the Python notebook (``NB_dbt_Runner``);
only the latter asks for ``evict_shadowed=True``.

Everything load-bearing about getting a bundle onto the driver lives here, not
in the notebook, so it is one copy, unit-tested (``tools/tests``), and ships
with the bundle it installs — the notebook can never run a bootstrap from a
different generation than its zip. Ported verbatim from the AANA Hub
repository (``scripts/fabric_bundle_bootstrap.py``), where the pattern runs in
production.

Design points (each answers a failure met in production):

* **Offline, exact, ``--no-deps``.** The publish script already resolved the
  full closure against the runtime's package manifest and pruned every wheel
  the runtime ships at the same version. What is left is installed verbatim
  with ``pip install --no-index --no-deps``; nothing here can shadow a
  runtime package, and no resolver runs at session time.
* **Never ``%pip``.** On the Spark kernel ``%pip`` distributes to executors,
  restarts the Python interpreter (wiping every notebook parameter), and is
  disabled by default in pipeline runs. Plain ``pip --target`` on the driver
  does none of that; dbt is driver-only.
* **Python-version assert.** The wheels were built for the driver Python the
  publisher targeted (``deployment.json.wheel_python_version``); a runtime
  upgrade that moves it fails here with the fix in the message, instead of a
  ``No matching distribution`` from pip.
* **Idempotent and race-free.** Extraction and install targets are keyed by
  the bundle's commit and built into a ``.partial`` sibling that is renamed
  into place with a ``.complete`` marker. A second notebook on the same
  driver (high-concurrency sessions) reuses the result or, if it lost the
  race, discards its own partial — no half-written site dir under a live import.

Standard library only: this file runs before anything is installed.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_SCRATCH_ROOT = "/tmp"  # noqa: S108 — Fabric driver-local scratch disk, session-scoped
COMPLETE_MARKER = ".complete"
DEPLOYMENT_FILE = "deployment.json"
WHEELS_DIR = "wheels"
REQUIREMENTS_FILE = "requirements.txt"


@dataclass(frozen=True)
class BundleContext:
    """What :func:`bootstrap` leaves behind for the notebook."""

    bundle_dir: Path  # extracted zip root (code tree + deployment.json + wheels/)
    site_dir: Path  # pip --target dir now on sys.path
    deployment: dict
    extracted: bool  # False when a previous bootstrap's extraction was reused
    installed: bool  # False when a previous bootstrap's install was reused
    seconds: float


class BundleBootstrapError(RuntimeError):
    """A bundle cannot be used on this driver; the message says how to fix it."""


def bootstrap(
    zip_path: str | os.PathLike[str],
    *,
    scratch_root: str | os.PathLike[str] = DEFAULT_SCRATCH_ROOT,
    python: str = sys.executable,
    add_to_sys_path: bool = True,
    evict_shadowed: bool = False,
    quiet: bool = False,
) -> BundleContext:
    """Extract ``zip_path`` and install its ``wheels/`` for this interpreter.

    Returns the extracted bundle directory (the code tree) and the site dir
    the wheels were installed into. Raises :class:`BundleBootstrapError` when
    the zip is not a bundle or was built for a different driver Python.

    ``evict_shadowed`` additionally drops from ``sys.modules`` every module the
    kernel imported *before* this call from a distribution the bundle now
    shadows (see :func:`evict_shadowed_modules`). The Python-notebook kernel
    needs it: ``notebookutils`` imports ``azure.core`` at startup, and putting a
    newer azure-core first on ``sys.path`` changes nothing for a module that is
    already loaded. Off by default for the Spark kernel, where the bundle
    replaces nothing PySpark holds a reference to.
    """
    started = time.monotonic()
    zip_path = Path(zip_path)
    stem = zip_path.stem
    scratch = Path(scratch_root)

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        deployment = _read_deployment(archive, names, zip_path)
        if f"{WHEELS_DIR}/{REQUIREMENTS_FILE}" not in names:
            raise BundleBootstrapError(
                f"{zip_path.name} carries no {WHEELS_DIR}/{REQUIREMENTS_FILE}; it was "
                "published by an older script. Republish it."
            )
        _check_python(deployment, zip_path)
        key = bundle_key(deployment)
        bundle_dir = scratch / stem / key
        extracted = _materialize(bundle_dir, archive.extractall)

    site_dir = scratch / f"{stem}_site" / key
    wheels_dir = bundle_dir / WHEELS_DIR
    installed = _materialize(site_dir, lambda target: _pip_install(python, wheels_dir, target))

    evicted: list[str] = []
    if add_to_sys_path:
        site = str(site_dir)
        if site not in sys.path:
            sys.path.insert(0, site)
        if evict_shadowed:
            evicted = evict_shadowed_modules(site_dir)
        importlib.invalidate_caches()
    drift = pruned_package_drift(deployment)

    seconds = time.monotonic() - started
    if not quiet:
        wheel_count = len(deployment.get("wheel_requirements") or [])
        print(
            f"Bundle {zip_path.name}: build_version={deployment.get('build_version') or '<none>'} "
            f"commit={(deployment.get('commit') or '<none>')[:12]} "
            f"runtime={deployment.get('runtime_version') or '?'} "
            f"(py{deployment.get('wheel_python_version') or '?'}) "
            f"wheels={wheel_count} {'installed' if installed else 'reused'} "
            f"in {seconds:.1f}s -> {site_dir}",
            flush=True,
        )
        if evicted:
            tops = sorted({name.split(".")[0] for name in evicted})
            print(
                f"Evicted {len(evicted)} pre-imported module(s) the bundle shadows "
                f"({', '.join(tops)}); they re-import from the bundle.",
                flush=True,
            )
        for line in drift:
            print(f"WARNING: {line}", flush=True)
        if drift:
            print(
                "WARNING: the runtime manifest the bundle was resolved against does not match this "
                "kernel. If dbt fails to import, refresh tools/runtime_constraints "
                "(tools/refresh_runtime_constraints.py) and republish.",
                flush=True,
            )
    return BundleContext(
        bundle_dir=bundle_dir,
        site_dir=site_dir,
        deployment=deployment,
        extracted=extracted,
        installed=installed,
        seconds=seconds,
    )


def pruned_package_drift(deployment: dict) -> list[str]:
    """Where this kernel disagrees with the manifest the bundle trusted.

    The publisher pruned every wheel the runtime manifest said the image ships
    at the same version, so those packages are *not* in the bundle and dbt
    imports the kernel's copy. If the image actually running is older or newer
    than the manifest (Microsoft's release notes are published ahead of the
    rollout), that copy may not be the version dbt was resolved against. This
    compares the pruned pins with what ``importlib.metadata`` sees and returns
    one human-readable line per mismatch - a warning, not a failure, because
    most drift is harmless and dbt's own import error is the real verdict.
    """
    from importlib import metadata

    drift: list[str] = []
    for pin in deployment.get("pruned_runtime_packages") or []:
        name, _, expected = str(pin).partition("==")
        if not name or not expected:
            continue
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            drift.append(f"{name}: not installed in this kernel, but the bundle relies on the runtime's {expected}")
            continue
        if actual != expected:
            drift.append(f"{name}: this kernel has {actual}, the bundle was resolved against the runtime's {expected}")
    return drift


def bundled_top_level_names(site_dir: Path) -> set[str]:
    """Import names the wheels installed into ``site_dir`` provide.

    Read from each distribution's ``top_level.txt``; distributions without one
    fall back to the package directories and modules at the root of the site
    dir. Namespace roots such as ``azure`` are included on purpose: evicting
    ``azure`` and ``azure.core`` together is what lets ``azure.core`` re-import
    from the bundle.
    """
    names: set[str] = set()
    for top_level in site_dir.glob("*.dist-info/top_level.txt"):
        names.update(line.strip() for line in top_level.read_text(encoding="utf-8").splitlines() if line.strip())
    for entry in site_dir.iterdir():
        if entry.name.endswith((".dist-info", ".pth", ".txt")) or entry.name == "bin" or entry.name.startswith((".", "_")):
            continue
        if entry.is_dir():
            names.add(entry.name)
        elif entry.suffix in {".py", ".pyd", ".so"}:
            names.add(entry.name.split(".")[0])
    return {n for n in names if n and n != "__pycache__"}


def evict_shadowed_modules(site_dir: Path) -> list[str]:
    """Drop already-imported modules that ``site_dir`` (now first on ``sys.path``) shadows.

    ``sys.path`` only governs *future* imports. A module the kernel loaded
    before the bootstrap - the Python-notebook kernel imports ``notebookutils``,
    which imports the runtime's azure-core - stays loaded, and a later
    ``from azure.core.credentials import AccessTokenInfo`` inside dbt-fabric
    fails against the old copy. Removing those entries from ``sys.modules``
    makes the next import resolve through ``sys.path`` again, i.e. to the
    bundle. Code that already holds references to the old module objects keeps
    working with them. Modules already loaded from ``site_dir`` are left alone.
    Returns the evicted module names.
    """
    site_prefix = os.path.normcase(str(site_dir.resolve())) + os.sep
    tops = bundled_top_level_names(site_dir)
    evicted: list[str] = []
    # Children before parents: a namespace package's ``__path__`` is recomputed
    # lazily from ``sys.modules[parent]``, so touching ``azure.core`` after
    # ``azure`` is gone raises KeyError. Only ``__file__`` is consulted; a
    # namespace package (no ``__file__``) is always evicted so its path list is
    # rebuilt with the bundle's directory in front.
    for name in sorted(sys.modules, key=lambda n: (-n.count("."), n)):
        top = name.split(".", 1)[0]
        if top not in tops:
            continue
        module = sys.modules.get(name)
        module_file = getattr(module, "__file__", None)
        if module_file and os.path.normcase(os.path.abspath(module_file)).startswith(site_prefix):
            continue  # already the bundle's copy
        del sys.modules[name]
        evicted.append(name)
    return sorted(evicted)


def bundle_key(deployment: dict) -> str:
    """Directory-safe identity of a bundle: its commit, else its publish time."""
    commit = str(deployment.get("commit") or "").strip()
    if commit:
        return commit[:12]
    stamp = str(deployment.get("published_utc") or "").strip()
    return re.sub(r"[^0-9A-Za-z]+", "", stamp) or "unversioned"


def _read_deployment(archive: zipfile.ZipFile, names: set[str], zip_path: Path) -> dict:
    if DEPLOYMENT_FILE not in names:
        raise BundleBootstrapError(f"{zip_path.name} carries no {DEPLOYMENT_FILE}; not a bundle.")
    try:
        deployment = json.loads(archive.read(DEPLOYMENT_FILE).decode("utf-8"))
    except ValueError as exc:
        raise BundleBootstrapError(f"{zip_path.name}: {DEPLOYMENT_FILE} is not valid JSON") from exc
    if not isinstance(deployment, dict):
        raise BundleBootstrapError(f"{zip_path.name}: {DEPLOYMENT_FILE} must be a JSON object")
    return deployment


def _check_python(deployment: dict, zip_path: Path) -> None:
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    built_for = str(deployment.get("wheel_python_version") or "").strip()
    if built_for != running:
        raise BundleBootstrapError(
            f"{zip_path.name} was built for Python {built_for or '<unknown>'} "
            f"(Fabric runtime '{deployment.get('runtime_version') or '<unknown>'}') but this "
            f"kernel runs Python {running}. Republish it with --runtime set to the profile that "
            "matches this notebook (a PySpark notebook: the runtime the workspace's Spark settings "
            "select; a Python notebook: the kernel its metadata names), or move the notebook to "
            "the runtime the bundle was built for."
        )


def _pip_install(python: str, wheels_dir: Path, target: Path) -> None:
    command = [
        python, "-m", "pip", "install",
        "--quiet", "--no-index", "--no-deps",
        "--find-links", str(wheels_dir),
        "--target", str(target),
        "-r", str(wheels_dir / REQUIREMENTS_FILE),
    ]
    result = subprocess.run(command, capture_output=True, text=True)  # noqa: S603 — fixed argv, no shell
    if result.returncode != 0:
        raise BundleBootstrapError(
            "pip install of the wheel bundle failed:\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-4000:]}"
        )


def _materialize(target: Path, build: Callable[[Path], None]) -> bool:
    """Build ``target`` once, atomically. Returns False when it already existed.

    ``build`` fills a ``.partial`` sibling; the marker is written inside it and
    the directory is renamed into place. If a concurrent caller renamed first,
    the rename fails, the marker is found, and this caller's partial is dropped.
    """
    marker = target / COMPLETE_MARKER
    if marker.is_file():
        return False
    partial = target.with_name(f"{target.name}.partial-{os.getpid()}")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    try:
        build(partial)
        (partial / COMPLETE_MARKER).write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
        try:
            partial.rename(target)
        except OSError:
            if marker.is_file():
                shutil.rmtree(partial, ignore_errors=True)
                return False
            raise
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return True
