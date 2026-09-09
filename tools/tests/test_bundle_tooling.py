"""Unit tests for the publish-side bundle tooling (onelake_bundle, refresh_runtime_constraints, publish_dbt_bundle)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import onelake_bundle as ob
import publish_dbt_bundle
import pytest
import refresh_runtime_constraints as rrc

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_normalize_name_is_pep503():
    assert ob.normalize_name("Ruamel.YAML") == "ruamel-yaml"
    assert ob.normalize_name("typing_extensions") == "typing-extensions"
    assert ob.normalize_name("dbt-fabricspark") == "dbt-fabricspark"


def test_parse_wheel_filename_handles_build_tags():
    assert ob.parse_wheel_filename("jaffle_dbt_runner-1.0.0-py3-none-any.whl") == ("jaffle-dbt-runner", "1.0.0")
    assert ob.parse_wheel_filename("protobuf-6.31.1-cp39-abi3-manylinux2014_x86_64.whl") == ("protobuf", "6.31.1")
    assert ob.parse_wheel_filename("pkg-1.0-1-py3-none-any.whl") == ("pkg", "1.0")
    with pytest.raises(ValueError):
        ob.parse_wheel_filename("not-a-wheel.txt")


def test_versions_equal_normalizes():
    assert ob.versions_equal("2.9.0.post0", "2.9.0.post0")
    assert not ob.versions_equal("6.31.1", "6.33.6")


def test_manifest_parser_maps_conda_and_pip_entries():
    manifest = """
name: fabric
dependencies:
  - python=3.13.11=h123_0
  - protobuf=5.29.6=py313hfdae721_0
  - opentelemetry-api=1.16.0=pyhd8ed1ab_0
  - typing_extensions=4.16.0=pyhcf101f3_0
  - msgpack-python=1.2.1=py313_0
  - tzdata=2025c=h04d1e81_0
  - libabseil=20250127.1=cxx17_hbbce691_0
  - openssl=3.5.1w=h123_0
  - pip:
      - pyspark==4.1.1.5.5.20260428.5
      - notebookutils==1.2.3
"""
    pins = rrc.parse_manifest(manifest)
    assert pins["protobuf"] == "5.29.6"
    assert pins["opentelemetry-api"] == "1.16.0"
    assert pins["typing-extensions"] == "4.16.0"
    assert pins["msgpack"] == "1.2.1"  # conda rename
    assert pins["pyspark"] == "4.1.1.5.5.20260428.5"
    assert pins["notebookutils"] == "1.2.3"
    for skipped in ("python", "tzdata", "libabseil", "openssl"):
        assert skipped not in pins


def test_vendored_constraints_exist_for_every_runtime_profile():
    for profile in ob.RUNTIME_PROFILES.values():
        pins, header = ob.load_constraints(profile)
        assert len(pins) > 100, profile.version
        assert header["manifest_sha256"]
        assert "protobuf" in pins and "pyspark" in pins


def test_read_requirements_in_keeps_only_requirements(tmp_path):
    path = tmp_path / "x.in"
    path.write_text(
        "# header\n-r other.in\n--index-url https://example\n\ndbt-core~=1.11.0  # inline\ndbt-fabricspark==1.13.4\n",
        encoding="utf-8",
    )
    assert ob.read_requirements_in(path) == ["dbt-core~=1.11.0", "dbt-fabricspark==1.13.4"]
    path.write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="No requirements"):
        ob.read_requirements_in(path)


def test_bundle_requirements_come_from_the_lakehouse_in_file():
    # The laptop venv, CI and the bundle share one adapter pin.
    expected = ob.read_requirements_in(REPO_ROOT / "requirements" / "lakehouse.in")
    assert list(publish_dbt_bundle.SPEC.requirements) == expected
    assert any(r.startswith("dbt-fabricspark==") for r in expected), "the adapter must be pinned exactly"
    assert not any(r.startswith(("pytest", "pip", "azure-storage")) for r in expected), (
        "publish-side tools belong in requirements/tools.in, not in the bundle"
    )


def test_publish_spec_targets_a_known_runtime_and_pins_protobuf():
    assert publish_dbt_bundle.SPEC.default_runtime in ob.RUNTIME_PROFILES
    assert publish_dbt_bundle.CONSTRAINT_OVERRIDES["protobuf"].specifier == "==6.31.1"
    assert all(o.reason for o in publish_dbt_bundle.CONSTRAINT_OVERRIDES.values())
    assert publish_dbt_bundle.SPEC.first_party_dirs == [REPO_ROOT / "runner"]
    assert (REPO_ROOT / "runner" / "pyproject.toml").is_file()


def test_collect_tree_filters_and_prefixes(tmp_path):
    (tmp_path / "models" / "marts").mkdir(parents=True)
    (tmp_path / "models" / "marts" / "customers.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".user.yml").write_text("id: x", encoding="utf-8")
    entries = ob.collect_tree(
        tmp_path, prefix="p/",
        excluded_dirs=publish_dbt_bundle.EXCLUDED_DIR_NAMES,
        excluded_files=publish_dbt_bundle.EXCLUDED_FILE_NAMES,
    )
    assert [arc for _, arc in entries] == ["p/models/marts/customers.sql"]


def test_write_bundle_adds_bootstrap_and_rejects_reserved_names(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "requirements.txt").write_text("", encoding="utf-8")
    code = tmp_path / "dbt_project.yml"
    code.write_text("name: jaffle_shop", encoding="utf-8")

    payload, count = ob.write_bundle([(code, "dbt_project.yml")], {"project": "t"}, wheels)
    names = set(zipfile.ZipFile(io.BytesIO(payload)).namelist())
    assert names == {"dbt_project.yml", "deployment.json", "bundle_bootstrap.py", "wheels/requirements.txt"}
    assert count == 3

    with pytest.raises(SystemExit, match="must not contain"):
        ob.write_bundle([(code, "bundle_bootstrap.py")], {}, wheels)


def test_lakehouse_files_prefix_by_name_or_guid():
    assert ob.lakehouse_files_prefix("LH_Jaffle_Shop") == "LH_Jaffle_Shop.Lakehouse/Files"
    assert ob.lakehouse_files_prefix("0123abcd-0123-4567-89ab-0123456789ab") == "0123abcd-0123-4567-89ab-0123456789ab/Files"
