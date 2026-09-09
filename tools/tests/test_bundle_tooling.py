"""Unit tests for the publish-side bundle tooling (onelake_bundle, refresh_runtime_constraints, publish_dbt_bundle)."""

from __future__ import annotations

import io
import json
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


def test_release_markdown_parser_reads_one_kernel_table_and_takes_the_shipped_version():
    """The Python-notebook image publishes a release note with one table per kernel."""
    note = """# System Environment
*   **VHD Name**: x.vhd

# Components
|Name|Version|
|-----|-----|
|**Notebookutils**|**2.1.6 ⬆️ 2.1.8**|

# Python3.10
|Name|Version|Name|Version|
|-----|-----|-----|-----|
|azure-core|1.20.0|pyodbc|4.0.39|

# Python3.11
|Name|Version|Name|Version|
|-----|-----|-----|-----|
|azure-core|1.29.4|**protobuf**|**5.29.3 ⬆️ 6.33.6**|
|**azure-identity**|**1.17.1**|pyodbc|4.0.39|
|typing_extensions|4.15.0|libprotobuf|5.29.3|
|**ca-certificates**|**2025.8.3 ⬆️ 2026.5.20**|**notebookutils**|**2.1.6 ⬆️ 2.1.8**|
|openssl|3.5.1w|python|3.11.13|

# Python3.12
|Name|Version|Name|Version|
|-----|-----|-----|-----|
|azure-core|1.40.0|pyodbc|5.3.0|
"""
    pins = rrc.parse_release_markdown(note, "Python3.11")
    assert pins["azure-core"] == "1.29.4"  # not the 3.10 or 3.12 table
    assert pins["protobuf"] == "6.33.6"  # upgraded entry: the version the release ships
    assert pins["azure-identity"] == "1.17.1"  # bold without an arrow (new package)
    assert pins["typing-extensions"] == "4.15.0"
    assert pins["notebookutils"] == "2.1.8"
    for skipped in ("libprotobuf", "ca-certificates", "openssl", "python", "name"):
        assert skipped not in pins
    with pytest.raises(SystemExit, match="Python3.9"):
        rrc.parse_release_markdown(note, "Python3.9")


def test_newest_release_note_picks_the_latest_dated_file():
    listing = json.dumps([
        {"name": "Candidate-Spark100.0-Rel-2026-03-01.0-rc.1.md", "type": "file", "download_url": "https://x/old.md"},
        {"name": "Candidate-Spark100.0-Rel-2026-06-01.0-rc.1.md", "type": "file", "download_url": "https://x/new.md"},
        {"name": "images", "type": "dir", "download_url": None},
    ])
    assert rrc.newest_release_note(listing, "https://api/x") == "https://x/new.md"
    with pytest.raises(SystemExit, match="No .md"):
        rrc.newest_release_note("[]", "https://api/x")


def test_vendored_constraints_exist_for_every_runtime_profile():
    for profile in ob.RUNTIME_PROFILES.values():
        pins, header = ob.load_constraints(profile)
        assert len(pins) > 100, profile.version
        assert header["manifest_sha256"]
        assert "protobuf" in pins
        if profile.manifest_format == "conda-yml":
            assert "pyspark" in pins, profile.version
        else:
            assert header["manifest_section"] == profile.manifest_section
            # what the Python-notebook kernel preloads and the bundle must be resolved against
            assert "notebookutils" in pins and "azure-core" in pins, profile.version
    assert ob.RUNTIME_PROFILES["python-3.11"].python_version == "3.11"
    assert ob.RUNTIME_PROFILES["2.0"].python_version == "3.13"


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


def test_bundle_requirements_come_from_the_requirements_in_files():
    # The laptop venvs, CI and the bundles share one adapter pin per target.
    spark = publish_dbt_bundle.SPECS["spark"]
    assert list(spark.requirements) == ob.read_requirements_in(REPO_ROOT / "requirements" / "lakehouse.in")
    assert any(r.startswith("dbt-fabricspark==") for r in spark.requirements), "the adapter must be pinned exactly"

    python = publish_dbt_bundle.SPECS["python"]
    adapters = {r.split("==")[0] for r in python.requirements if "==" in r}
    assert adapters == {"dbt-fabric", "dbt-fabricspark", "dbt-sqlserver[azure]"}
    assert sum(r.startswith("dbt-core") for r in python.requirements) == 1, "one dbt-core for all three adapters"
    for spec in publish_dbt_bundle.SPECS.values():
        assert not any(r.startswith(("pytest", "pip", "azure-storage")) for r in spec.requirements), (
            "publish-side tools belong in requirements/tools.in, not in the bundle"
        )


def test_publish_specs_target_known_runtimes_with_reasoned_overrides():
    names, destinations = set(), set()
    for key, spec in publish_dbt_bundle.SPECS.items():
        assert spec.default_runtime in ob.RUNTIME_PROFILES, key
        assert all(o.reason for o in spec.overrides.values()), key
        assert spec.first_party_dirs == [REPO_ROOT / "runner"]
        assert spec.default_destination.startswith("dbt/") and spec.consumer, key
        names.add(spec.name)
        destinations.add(spec.default_destination)
    assert len(names) == len(destinations) == len(publish_dbt_bundle.SPECS), "each bundle has its own zip"
    assert publish_dbt_bundle.SPECS["spark"].default_runtime == "2.0"
    assert publish_dbt_bundle.SPARK_OVERRIDES["protobuf"].specifier == "==6.31.1"
    assert publish_dbt_bundle.SPECS["python"].default_runtime == "python-3.11"
    assert {"azure-core", "azure-identity", "pyodbc"} <= set(publish_dbt_bundle.PYTHON_OVERRIDES)
    assert (REPO_ROOT / "runner" / "pyproject.toml").is_file()


def test_parse_args_runner_selects_spec_and_its_defaults():
    args, spec = publish_dbt_bundle.parse_args(["--assemble-only"])
    assert spec is publish_dbt_bundle.SPECS["spark"]
    assert (args.runtime, args.destination) == ("2.0", "dbt/jaffle_shop.zip")

    args, spec = publish_dbt_bundle.parse_args(["--runner", "python", "--assemble-only"])
    assert spec is publish_dbt_bundle.SPECS["python"]
    assert (args.runtime, args.destination) == ("python-3.11", "dbt/jaffle_shop_python.zip")
    assert args.lakehouse == "LH_Jaffle_Shop"

    args, _ = publish_dbt_bundle.parse_args(["--runner", "python", "--runtime", "2.0", "--destination", "x/y.zip", "--assemble-only"])
    assert (args.runtime, args.destination) == ("2.0", "x/y.zip")  # explicit flags still win


def test_merged_requirements_dedupes_preserving_order():
    merged = publish_dbt_bundle.merged_requirements("warehouse", "lakehouse", "sqldb")
    assert merged[0].startswith("dbt-core")
    assert len(merged) == len(set(merged))
    assert [r.split("==")[0] for r in merged[1:]] == ["dbt-fabric", "dbt-fabricspark", "dbt-sqlserver[azure]"]


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
