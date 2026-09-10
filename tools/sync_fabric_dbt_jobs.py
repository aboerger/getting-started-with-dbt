"""Copy the dbt project into the Fabric dbt job items so they run it as their own code.

Fabric's dbt job can be connected to a GitHub repository, but that mode could
not be made to run this project (2026-09-10): with the project in ``jaffle_shop/``
it reported ``20418: The project yaml file was not found``, and with a generated
branch that had the project at the root it reported ``20407: Failed to download
dbt project`` and gives no log of what it choked on. The mode that is known to
work is the one a dbt job starts in: the project lives **inside the item**
(``projectType: OneLake``), and Fabric's Git integration syncs it as
``workspace/<item>.DataBuildToolJob/Code/dbt/``.

So the code still exists once, in ``jaffle_shop/``, and this script derives the
items' copies from it - the same way ``tools/publish_dbt_bundle.py`` derives the
notebooks' bundles. Redundant on disk, one source of truth in practice: CI runs
``--check`` and fails a pull request whose copies are stale.

    python tools/sync_fabric_dbt_jobs.py            # rewrite Code/dbt/ in every DBT_* item
    python tools/sync_fabric_dbt_jobs.py --check    # exit 1 if any copy differs (CI)

What goes into ``Code/dbt/``:

- the project tree minus what a Fabric run does not need or must not see:
  ``seeds/`` (seeds are disabled in the jobs; the raw tables are loaded once,
  separately, and the CSVs are 16 MB), ``profiles.yml`` (Fabric generates the
  profile from the item's connection), ``target/``, ``logs/``, ``.user.yml``,
  ``.gitignore``;
- ``dbt_packages/`` from ``dbt deps``, pruned to what dbt loads at run time
  (``dbt_project.yml`` + ``macros/`` per package): the job editor says package
  dependencies are not supported, i.e. the runtime does not run ``dbt deps`` -
  vendoring them is what makes ``dbt_utils`` resolve;
- nothing Fabric's Git integration rejects: zero-byte files (``.gitkeep``) and
  files without an extension (a package's ``LICENSE``) are skipped;
- ``GENERATED.md`` naming the source so nobody edits the copy.

The item's ``dbt-content.json`` gets ``project = {projectType: OneLake,
folderPath: dbt}`` (what a freshly created job has); profile and command are
left untouched.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = REPO_ROOT / "jaffle_shop"
WORKSPACE_DIR = REPO_ROOT / "workspace"
ITEM_GLOB = "DBT_*.DataBuildToolJob"
CODE_SUBDIR = Path("Code") / "dbt"
GENERATED_NOTE = "GENERATED.md"

EXCLUDED_DIRS = {"target", "logs", "seeds", "dbt_packages", "__pycache__"}
EXCLUDED_FILES = {"profiles.yml", ".user.yml", ".gitignore"}
# Inside each vendored package: what dbt reads at run time.
PACKAGE_KEEP_DIRS = {"macros"}
PACKAGE_KEEP_FILES = {"dbt_project.yml"}


def fabric_accepts(path: Path) -> bool:
    """Fabric's Git integration refuses an item update that carries a zero-byte
    file or a file without an extension ("at least one invalid file in Git for
    the item", 2026-09-10: `analyses/.gitkeep`, `dbt_packages/dbt_utils/LICENSE`).
    dbt needs neither, so they stay out of the copy."""
    return path.stat().st_size > 0 and bool(path.suffix)


def copy_project(project_dir: Path, dest: Path) -> list[str]:
    """Copy the project tree into ``dest`` minus the exclusions; return relative paths."""
    copied: list[str] = []
    for path in sorted(project_dir.rglob("*")):
        relative = path.relative_to(project_dir)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if not path.is_file() or path.name in EXCLUDED_FILES or not fabric_accepts(path):
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(relative.as_posix())
    return copied


def resolve_packages(project_dir: Path, work: Path) -> Path | None:
    """``dbt deps`` for the project in a scratch copy; returns its dbt_packages/ or None."""
    if not any((project_dir / name).is_file() for name in ("packages.yml", "dependencies.yml")):
        return None
    scratch = work / "deps"
    scratch.mkdir()
    for name in ("dbt_project.yml", "packages.yml", "dependencies.yml", "package-lock.yml", "profiles.yml"):
        if (project_dir / name).is_file():
            shutil.copyfile(project_dir / name, scratch / name)
    try:
        import truststore

        truststore.inject_into_ssl()  # corporate proxy CA lives in the OS store
    except ImportError:
        pass
    try:
        from dbt.cli.main import dbtRunner
    except ImportError as exc:
        raise SystemExit("dbt is not importable here; run from .venv-tools (tools\\setup-env.ps1 -Target tools).") from exc
    res = dbtRunner().invoke([
        "deps", "--project-dir", str(scratch), "--profiles-dir", str(scratch),
        "--log-path", str(work / "dbt-logs"), "--quiet", "--no-send-anonymous-usage-stats",
    ])
    if not res.success:
        raise SystemExit(f"dbt deps failed: {res.exception}")
    packages = scratch / "dbt_packages"
    if not packages.is_dir():
        raise SystemExit("dbt deps ran but produced no dbt_packages/")
    return packages


def vendor_packages(packages_dir: Path, dest: Path) -> list[str]:
    """Copy each package's run-time files (dbt_project.yml, macros/, LICENSE) into ``dest/dbt_packages``."""
    copied: list[str] = []
    for package in sorted(p for p in packages_dir.iterdir() if p.is_dir()):
        for path in sorted(package.rglob("*")):
            relative = path.relative_to(package)
            keep = (len(relative.parts) == 1 and relative.name in PACKAGE_KEEP_FILES) or (
                relative.parts[0] in PACKAGE_KEEP_DIRS
            )
            if not keep or not path.is_file() or not fabric_accepts(path):
                continue
            target = dest / "dbt_packages" / package.name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            copied.append((Path("dbt_packages") / package.name / relative).as_posix())
    return copied


def write_note(dest: Path, source_label: str) -> None:
    (dest / GENERATED_NOTE).write_text(
        "# Generated copy, do not edit\n\n"
        f"This folder is `{source_label}` copied by `tools/sync_fabric_dbt_jobs.py` so the Fabric dbt job item "
        "runs it as its own project (`projectType: OneLake`). `dbt_packages/` is the resolved `dbt deps` output, "
        "trimmed to what dbt loads at run time; `seeds/` and `profiles.yml` are left out on purpose (seeds are "
        "disabled in the jobs, Fabric generates the profile). Change the project on `main`, then run the sync; "
        "CI fails a pull request whose copies are stale (`--check`).\n",
        encoding="utf-8",
    )


def build_code_tree(project_dir: Path, dest: Path, packages_dir: Path | None, source_label: str) -> list[str]:
    files = copy_project(project_dir, dest)
    if packages_dir is not None:
        files += vendor_packages(packages_dir, dest)
    write_note(dest, source_label)
    files.append(GENERATED_NOTE)
    return sorted(files)


def trees_differ(built: Path, existing: Path) -> list[str]:
    """Relative paths that differ between two trees (missing, extra, or different bytes)."""
    if not existing.is_dir():
        return ["<missing>"]
    built_files = {p.relative_to(built).as_posix() for p in built.rglob("*") if p.is_file()}
    existing_files = {p.relative_to(existing).as_posix() for p in existing.rglob("*") if p.is_file()}
    differing = sorted(built_files ^ existing_files)
    for relative in sorted(built_files & existing_files):
        if not filecmp.cmp(built / relative, existing / relative, shallow=False):
            differing.append(relative)
    return differing


def update_content_json(item_dir: Path) -> bool:
    """Point the item at its own Code/dbt folder; return True if the file changed."""
    path = item_dir / "dbt-content.json"
    content = json.loads(path.read_text(encoding="utf-8"))
    wanted = {"projectType": "OneLake", "folderPath": CODE_SUBDIR.name}
    if content.get("project") == wanted:
        return False
    content["project"] = wanted
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return True


def job_items(workspace_dir: Path) -> list[Path]:
    return sorted(p for p in workspace_dir.glob(ITEM_GLOB) if (p / "dbt-content.json").is_file())


def sync(
    project_dir: Path = PROJECT_DIR,
    workspace_dir: Path = WORKSPACE_DIR,
    *,
    check: bool = False,
    run_deps: bool = True,
    packages_dir: Path | None = None,
) -> int:
    """Rewrite (or, with ``check``, compare) Code/dbt in every dbt job item. Returns a process exit code."""
    items = job_items(workspace_dir)
    if not items:
        raise SystemExit(f"No {ITEM_GLOB} items with dbt-content.json under {workspace_dir}")
    source_label = f"{project_dir.relative_to(project_dir.parent).as_posix()}/"
    stale = 0
    with tempfile.TemporaryDirectory(prefix="fabric-dbt-jobs-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        if packages_dir is None and run_deps:
            packages_dir = resolve_packages(project_dir, work)
        built = work / "built"
        built.mkdir()
        files = build_code_tree(project_dir, built, packages_dir, source_label)
        for item in items:
            code_dir = item / CODE_SUBDIR
            differing = trees_differ(built, code_dir)
            content_wanted = json.loads((item / "dbt-content.json").read_text(encoding="utf-8")).get("project") != {
                "projectType": "OneLake", "folderPath": CODE_SUBDIR.name,
            }
            if check:
                if differing or content_wanted:
                    stale += 1
                    print(f"{item.name}: STALE ({len(differing)} file(s) differ" + (", dbt-content.json project" if content_wanted else "") + ")")
                    for relative in differing[:10]:
                        print(f"    {relative}")
                else:
                    print(f"{item.name}: in sync ({len(files)} files)")
                continue
            if differing:
                shutil.rmtree(code_dir, ignore_errors=True)
                shutil.copytree(built, code_dir)
            changed_json = update_content_json(item)
            print(
                f"{item.name}: {'updated' if differing else 'unchanged'} Code/dbt ({len(files)} files)"
                + ("; dbt-content.json -> OneLake project" if changed_json else "")
            )
    if check and stale:
        print(f"{stale} item(s) out of date: run `python tools/sync_fabric_dbt_jobs.py` and commit.")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Compare only; exit 1 when a copy is stale (CI).")
    parser.add_argument("--skip-deps", action="store_true", help="Do not vendor dbt_packages/ (offline).")
    args = parser.parse_args(argv)
    return sync(check=args.check, run_deps=not args.skip_deps)


if __name__ == "__main__":
    sys.exit(main())
