"""The snapshot branch builder, exercised against a throwaway git repository (no dbt, no network)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import sync_fabric_dbt_branch as sync


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tests")
    project = repo / "jaffle_shop"
    (project / "models").mkdir(parents=True)
    (project / "dbt_project.yml").write_text("name: jaffle_shop\n", encoding="utf-8")
    (project / "models" / "customers.sql").write_text("select 1", encoding="utf-8")
    (project / ".gitignore").write_text("target/\ndbt_packages/\n", encoding="utf-8")
    (repo / "README.md").write_text("repo readme, must not leak into the snapshot", encoding="utf-8")
    (repo / "tools").mkdir()
    (repo / "tools" / "x.py").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: first")
    # uncommitted junk in the work tree must not affect the snapshot
    (project / "target").mkdir()
    (project / "target" / "manifest.json").write_text("{}", encoding="utf-8")
    (project / "models" / "uncommitted.sql").write_text("select 2", encoding="utf-8")
    return repo


def test_snapshot_hoists_the_committed_project_to_the_root(repo: Path):
    commit, source = sync.build_snapshot(repo, branch="snap", run_deps=False)

    assert commit and source == _git(repo, "rev-parse", "HEAD")
    files = set(_git(repo, "ls-tree", "-r", "--name-only", "snap").splitlines())
    assert files == {"dbt_project.yml", "models/customers.sql", ".gitignore", "README.md"}
    readme = _git(repo, "show", "snap:README.md")
    assert source[:12] in readme and "do not edit" in readme and "feat: first" in readme
    assert _git(repo, "log", "--format=%s", "snap") == f"Snapshot of jaffle_shop/ at {source[:12]}: feat: first"
    # the work tree and the current branch are untouched
    assert _git(repo, "branch", "--show-current") == "main"
    assert (repo / "jaffle_shop" / "models" / "uncommitted.sql").is_file()
    assert not (repo / "dbt_project.yml").exists()


def test_snapshot_is_idempotent_and_appends_history(repo: Path):
    first, _ = sync.build_snapshot(repo, branch="snap", run_deps=False)
    again, _ = sync.build_snapshot(repo, branch="snap", run_deps=False)
    assert first and again is None  # same tree -> no new commit

    (repo / "jaffle_shop" / "models" / "orders.sql").write_text("select 3", encoding="utf-8")
    _git(repo, "add", "-A", "jaffle_shop/models/orders.sql")
    _git(repo, "commit", "-q", "-m", "feat: orders")
    second, _ = sync.build_snapshot(repo, branch="snap", run_deps=False)

    assert second and second != first
    assert _git(repo, "rev-parse", "snap^") == first  # fast-forward history, no force push needed
    assert "models/orders.sql" in _git(repo, "ls-tree", "-r", "--name-only", "snap")


def test_snapshot_vendors_ignored_dbt_packages_and_drops_dbt_byproducts(repo: Path, monkeypatch):
    def fake_deps(project_dir: Path, log_dir=None) -> None:
        (project_dir / "dbt_packages" / "dbt_utils").mkdir(parents=True)
        (project_dir / "dbt_packages" / "dbt_utils" / "dbt_project.yml").write_text("name: dbt_utils\n", encoding="utf-8")
        # what a real `dbt deps` leaves behind when not told otherwise
        (project_dir / "logs").mkdir()
        (project_dir / "logs" / "dbt.log").write_text("log", encoding="utf-8")
        (project_dir / ".user.yml").write_text("id: x\n", encoding="utf-8")
        (project_dir / "target").mkdir()
        assert log_dir is not None and log_dir.parent == project_dir.parent  # log next to, not inside, the snapshot

    monkeypatch.setattr(sync, "vendor_dbt_packages", fake_deps)
    sync.build_snapshot(repo, branch="snap", run_deps=True)
    files = set(_git(repo, "ls-tree", "-r", "--name-only", "snap").splitlines())
    assert "dbt_packages/dbt_utils/dbt_project.yml" in files  # despite .gitignore listing dbt_packages/
    assert not {f for f in files if f.startswith(("logs/", "target/")) or f == ".user.yml"}


def test_snapshot_leaves_out_files_over_the_github_contents_limit(repo: Path):
    seeds = repo / "jaffle_shop" / "seeds"
    seeds.mkdir()
    (seeds / "raw_orders.csv").write_text("id\n" + "x\n" * 600_000, encoding="utf-8")  # ~1.2 MB
    (seeds / "raw_customers.csv").write_text("id\n1\n", encoding="utf-8")
    _git(repo, "add", "-A", "jaffle_shop/seeds")
    _git(repo, "commit", "-q", "-m", "feat: seeds")

    sync.build_snapshot(repo, branch="snap", run_deps=False)

    files = set(_git(repo, "ls-tree", "-r", "--name-only", "snap").splitlines())
    assert "seeds/raw_customers.csv" in files
    assert "seeds/raw_orders.csv" not in files
    readme = _git(repo, "show", "snap:README.md")
    assert "seeds/raw_orders.csv" in readme and "1 MB" in readme


def test_snapshot_refuses_a_ref_without_the_project(repo: Path):
    with pytest.raises(SystemExit, match="dbt_project.yml"):
        sync.build_snapshot(repo, prefix="tools", branch="snap", run_deps=False)
