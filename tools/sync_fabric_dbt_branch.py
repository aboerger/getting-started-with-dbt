"""Publish the dbt project as a root-level snapshot branch for the Fabric dbt job items.

Fabric's GitHub-connected dbt job (``DBT_Jaffle_Shop_WH`` / ``_LH``) reads
``dbt_project.yml`` from the **root** of the branch it is pointed at; the
``folderPath`` in its definition did not make it look inside ``jaffle_shop/``
(runs kept failing with ``20418: The project yaml file was not found``). The
project stays where it is - one copy, next to ``requirements/``, ``runner/``
and ``tools/`` - and this script derives a branch from it:

    fabric-dbt-job
    ├── dbt_project.yml        <- jaffle_shop/ hoisted to the root
    ├── models/ macros/ ...
    ├── dbt_packages/          <- `dbt deps` output vendored (the job runtime
    │                             does not run dbt deps; packages.yml alone fails)
    ├── seeds/                 <- minus files over 1 MB (GitHub contents API limit;
    │                             the job downloads file by file and fails on them)
    └── README.md              <- "generated from <commit>, do not edit"

Each run appends one commit on top of the previous snapshot (fast-forward
pushes, an auditable history of what the jobs ran), or nothing when the
project tree is unchanged. ``.github/workflows/sync-fabric-dbt-branch.yml``
runs it on every push to ``main`` that touches the project; run it by hand
from ``.venv-tools`` when you need the branch updated now::

    python tools/sync_fabric_dbt_branch.py            # build the branch locally
    python tools/sync_fabric_dbt_branch.py --push     # ...and push it to origin

The work tree is never switched: the snapshot is assembled in a temp
directory (``git archive`` of the committed project, then ``dbt deps``) and
committed through a temporary index, so this is safe to run with uncommitted
changes in the checkout.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_PREFIX = "jaffle_shop"
SNAPSHOT_BRANCH = "fabric-dbt-job"
README_NAME = "README.md"
CONSUMERS = "the Fabric dbt job items DBT_Jaffle_Shop_WH and DBT_Jaffle_Shop_LH"


def git(*args: str, repo: Path, env: dict | None = None, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["git", *args], cwd=repo, capture_output=True, input=input_bytes,
        env={**os.environ, **(env or {})},
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.decode('utf-8', 'replace')[-2000:]}")
    return result.stdout.decode("utf-8", "replace").strip()


def export_project(repo: Path, ref: str, prefix: str, dest: Path) -> None:
    """``git archive <ref>:<prefix>`` into ``dest`` (committed files only)."""
    payload = subprocess.run(  # noqa: S603
        ["git", "archive", "--format=zip", f"{ref}:{prefix}"], cwd=repo, capture_output=True,
    )
    if payload.returncode != 0:
        raise SystemExit(f"git archive {ref}:{prefix} failed: {payload.stderr.decode('utf-8', 'replace')[-500:]}")
    zipfile.ZipFile(io.BytesIO(payload.stdout)).extractall(dest)
    scrub_dbt_byproducts(dest)


def vendor_dbt_packages(project_dir: Path, log_dir: Path | None = None) -> None:
    """``dbt deps`` into the snapshot so the job runtime never has to.

    dbt's own by-products (``logs/``, ``target/``, ``.user.yml``) are kept out of
    the snapshot: the log goes to ``log_dir`` and :func:`scrub_dbt_byproducts`
    runs afterwards.
    """
    if not any((project_dir / name).is_file() for name in ("packages.yml", "dependencies.yml")):
        return
    try:
        import truststore

        truststore.inject_into_ssl()  # corporate proxy CA lives in the OS store
    except ImportError:
        pass
    try:
        from dbt.cli.main import dbtRunner
    except ImportError as exc:
        raise SystemExit("dbt is not importable here; run from .venv-tools (tools\\setup-env.ps1 -Target tools).") from exc
    argv = [
        "deps", "--project-dir", str(project_dir), "--profiles-dir", str(project_dir),
        "--quiet", "--no-send-anonymous-usage-stats",
    ]
    if log_dir is not None:
        argv += ["--log-path", str(log_dir)]
    res = dbtRunner().invoke(argv)
    if not res.success:
        raise SystemExit(f"dbt deps failed: {res.exception}")
    if not (project_dir / "dbt_packages").is_dir():
        raise SystemExit("dbt deps ran but produced no dbt_packages/")


DBT_BYPRODUCT_DIRS = ("target", "logs")
DBT_BYPRODUCT_FILES = (".user.yml",)


def scrub_dbt_byproducts(project_dir: Path) -> None:
    """Remove what a dbt invocation leaves behind in a project directory."""
    for name in DBT_BYPRODUCT_DIRS:
        shutil.rmtree(project_dir / name, ignore_errors=True)
    for name in DBT_BYPRODUCT_FILES:
        (project_dir / name).unlink(missing_ok=True)


# GitHub's contents API returns no content for files above 1 MB (`encoding: none`),
# and the Fabric dbt job downloads the project file by file through it: a branch
# with the 7-9 MB seed CSVs fails with `20407: Failed to download dbt project`.
# Seeds are disabled in the Fabric jobs anyway (the raw tables are loaded once,
# separately), so anything over the limit stays out of the snapshot.
MAX_FILE_BYTES = 1_000_000


def drop_oversized_files(dest: Path, limit: int = MAX_FILE_BYTES) -> list[str]:
    """Delete files larger than ``limit`` under ``dest``; return their relative paths."""
    dropped: list[str] = []
    for path in sorted(dest.rglob("*")):
        if path.is_file() and path.stat().st_size > limit:
            dropped.append(path.relative_to(dest).as_posix())
            path.unlink()
    return dropped


def write_readme(dest: Path, source_commit: str, source_subject: str, branch: str, dropped: list[str] = ()) -> None:
    text = (
        f"# {branch}: generated branch, do not edit\n\n"
        f"Root-level snapshot of `{PROJECT_PREFIX}/` at commit `{source_commit}` ({source_subject}), "
        f"with `dbt_packages/` vendored, produced by `tools/sync_fabric_dbt_branch.py` for {CONSUMERS}. "
        "Those jobs read `dbt_project.yml` from the root of the branch they are connected to.\n\n"
        "Change the project on `main` (folder `jaffle_shop/`); the sync workflow republishes this branch.\n"
    )
    if dropped:
        text += (
            f"\n## Not included (larger than {MAX_FILE_BYTES:,} bytes)\n\n"
            "The Fabric dbt job fetches files through GitHub's contents API, which returns no content above "
            "1 MB. These files exist on `main` and are not needed by the jobs (seeds are disabled there):\n\n"
            + "".join(f"- `{path}`\n" for path in dropped)
        )
    (dest / README_NAME).write_text(text, encoding="utf-8")


def commit_snapshot(repo: Path, snapshot_dir: Path, branch: str, message: str) -> str | None:
    """Commit ``snapshot_dir`` as the next commit of ``branch`` without touching the work tree.

    Returns the new commit hash, or None when the tree equals the branch tip's.
    """
    parent = None
    try:
        parent = git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", repo=repo)
    except SystemExit:
        parent = None
    with tempfile.TemporaryDirectory(prefix="snapshot-index-") as index_dir:
        env = {"GIT_INDEX_FILE": str(Path(index_dir) / "index"), "GIT_WORK_TREE": str(snapshot_dir)}
        git("add", "-A", "-f", ".", repo=repo, env=env)  # -f: the project's .gitignore lists dbt_packages/
        tree = git("write-tree", repo=repo, env=env)
    if parent and git("rev-parse", f"{parent}^{{tree}}", repo=repo) == tree:
        return None
    args = ["commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    commit = git(*args, repo=repo)
    git("update-ref", f"refs/heads/{branch}", commit, repo=repo)
    return commit


def build_snapshot(
    repo: Path = REPO_ROOT,
    *,
    ref: str = "HEAD",
    prefix: str = PROJECT_PREFIX,
    branch: str = SNAPSHOT_BRANCH,
    run_deps: bool = True,
) -> tuple[str | None, str]:
    """Assemble and commit the snapshot; returns (new commit or None, source commit)."""
    source_commit = git("rev-parse", ref, repo=repo)
    source_subject = git("log", "-1", "--format=%s", source_commit, repo=repo)
    # dbt keeps its log file open after `dbt deps`; the log lives next to (not inside)
    # the snapshot and a locked file must not fail the run once the commit exists.
    with tempfile.TemporaryDirectory(prefix="fabric-dbt-snapshot-", ignore_cleanup_errors=True) as tmp:
        snapshot = Path(tmp) / "snapshot"
        snapshot.mkdir()
        export_project(repo, source_commit, prefix, snapshot)
        if not (snapshot / "dbt_project.yml").is_file():
            raise SystemExit(f"{prefix}/dbt_project.yml is not in commit {source_commit[:12]}")
        if run_deps:
            vendor_dbt_packages(snapshot, log_dir=Path(tmp) / "dbt-logs")
        scrub_dbt_byproducts(snapshot)
        dropped = drop_oversized_files(snapshot)
        for path in dropped:
            print(f"  not included (> {MAX_FILE_BYTES:,} bytes, GitHub contents API limit): {path}")
        write_readme(snapshot, source_commit, source_subject, branch, dropped)
        message = f"Snapshot of {prefix}/ at {source_commit[:12]}: {source_subject}"
        return commit_snapshot(repo, snapshot, branch, message), source_commit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="HEAD", help="Commit to snapshot (default: HEAD).")
    parser.add_argument("--branch", default=SNAPSHOT_BRANCH, help=f"Snapshot branch (default: {SNAPSHOT_BRANCH}).")
    parser.add_argument("--remote", default="origin", help="Remote for --push (default: origin).")
    parser.add_argument("--push", action="store_true", help="Push the branch after building it.")
    parser.add_argument("--skip-deps", action="store_true", help="Do not vendor dbt_packages/ (tests, offline).")
    args = parser.parse_args(argv)

    commit, source = build_snapshot(ref=args.ref, branch=args.branch, run_deps=not args.skip_deps)
    if commit:
        print(f"{args.branch}: new snapshot {commit[:12]} of {PROJECT_PREFIX}/ at {source[:12]}")
    else:
        print(f"{args.branch}: unchanged (already a snapshot of the current {PROJECT_PREFIX}/ tree)")
    if args.push:
        git("push", args.remote, f"refs/heads/{args.branch}:refs/heads/{args.branch}", repo=REPO_ROOT)
        print(f"pushed {args.branch} to {args.remote}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
