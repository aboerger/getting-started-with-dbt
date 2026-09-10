"""The dbt-job item sync, against a throwaway project and workspace (no dbt, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sync_fabric_dbt_jobs as sync


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def tree(tmp_path: Path):
    project = tmp_path / "jaffle_shop"
    _write(project / "dbt_project.yml", "name: jaffle_shop\n")
    _write(project / "packages.yml", "packages: []\n")
    _write(project / "package-lock.yml", "packages: []\n")
    _write(project / "profiles.yml", "secret-ish")
    _write(project / ".gitignore", "target/\n")
    _write(project / ".user.yml", "id: 1")
    _write(project / "models" / "marts" / "customers.sql", "select 1")
    _write(project / "macros" / "booleans.sql", "{% macro x() %}{% endmacro %}")
    _write(project / "seeds" / "jaffle-data" / "raw_orders.csv", "id\n1\n")
    _write(project / "target" / "manifest.json", "{}")
    _write(project / "logs" / "dbt.log", "log")
    _write(project / "analyses" / ".gitkeep", "")

    packages = tmp_path / "resolved_packages"
    _write(packages / "dbt_utils" / "dbt_project.yml", "name: dbt_utils\n")
    _write(packages / "dbt_utils" / "LICENSE", "Apache")
    _write(packages / "dbt_utils" / "macros" / "sql" / "star.sql", "{% macro star() %}{% endmacro %}")
    _write(packages / "dbt_utils" / "integration_tests" / "models" / "x.sql", "select 1")
    _write(packages / "dbt_utils" / "run_test.sh", "#!/bin/sh")

    workspace = tmp_path / "workspace"
    for name in ("DBT_Jaffle_Shop_WH", "DBT_Jaffle_Shop_LH"):
        item = workspace / f"{name}.DataBuildToolJob"
        _write(item / ".platform", "{}")
        _write(item / "dbt-content.json", json.dumps({
            "project": {"projectType": "GitHub", "branch": "fabric-dbt-job", "folderPath": "dbt",
                        "externalReferences": {"connection": "c0ffee"}},
            "profile": {"profileType": "DataWarehouse", "schema": "jaffle_shop"},
            "command": {"operation": "build", "arguments": {"threads": 4}},
        }, indent=2))
        _write(item / "Code" / "dbt" / "stale.sql", "old")
    _write(workspace / "LH_Jaffle_Shop.Lakehouse" / ".platform", "{}")  # not a dbt job
    return project, workspace, packages


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_sync_writes_the_trimmed_project_and_repoints_the_items(tree, capsys):
    project, workspace, packages = tree
    assert sync.sync(project, workspace, packages_dir=packages) == 0

    for name in ("DBT_Jaffle_Shop_WH", "DBT_Jaffle_Shop_LH"):
        item = workspace / f"{name}.DataBuildToolJob"
        assert _files(item / "Code" / "dbt") == {
            "dbt_project.yml", "packages.yml", "package-lock.yml",
            "models/marts/customers.sql", "macros/booleans.sql", "analyses/.gitkeep",
            "dbt_packages/dbt_utils/dbt_project.yml", "dbt_packages/dbt_utils/LICENSE",
            "dbt_packages/dbt_utils/macros/sql/star.sql",
            "GENERATED.md",
        }
        content = json.loads((item / "dbt-content.json").read_text(encoding="utf-8"))
        assert content["project"] == {"projectType": "OneLake", "folderPath": "dbt"}
        assert content["profile"]["schema"] == "jaffle_shop" and content["command"]["operation"] == "build"
    assert not (workspace / "LH_Jaffle_Shop.Lakehouse" / "Code").exists()
    out = capsys.readouterr().out
    assert "updated Code/dbt" in out and "OneLake project" in out


def test_check_mode_reports_stale_then_in_sync(tree, capsys):
    project, workspace, packages = tree
    assert sync.sync(project, workspace, check=True, packages_dir=packages) == 1
    assert "STALE" in capsys.readouterr().out
    # check mode never writes
    assert (workspace / "DBT_Jaffle_Shop_WH.DataBuildToolJob" / "Code" / "dbt" / "stale.sql").is_file()

    sync.sync(project, workspace, packages_dir=packages)
    assert sync.sync(project, workspace, check=True, packages_dir=packages) == 0
    assert "in sync" in capsys.readouterr().out

    (project / "models" / "marts" / "orders.sql").write_text("select 2", encoding="utf-8")
    assert sync.sync(project, workspace, check=True, packages_dir=packages) == 1
    assert "models/marts/orders.sql" in capsys.readouterr().out


def test_sync_is_idempotent(tree, capsys):
    project, workspace, packages = tree
    sync.sync(project, workspace, packages_dir=packages)
    capsys.readouterr()
    sync.sync(project, workspace, packages_dir=packages)
    out = capsys.readouterr().out
    assert out.count("unchanged Code/dbt") == 2 and "OneLake project" not in out


def test_sync_without_packages(tree):
    project, workspace, _ = tree
    (project / "packages.yml").unlink()
    (project / "package-lock.yml").unlink()
    assert sync.sync(project, workspace, run_deps=False) == 0
    files = _files(workspace / "DBT_Jaffle_Shop_WH.DataBuildToolJob" / "Code" / "dbt")
    assert not any(f.startswith("dbt_packages/") for f in files)


def test_sync_requires_job_items(tmp_path):
    with pytest.raises(SystemExit, match="No DBT_"):
        sync.sync(tmp_path / "p", tmp_path / "empty_ws", run_deps=False)
