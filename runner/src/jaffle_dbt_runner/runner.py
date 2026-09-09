"""Orchestration for one dbt invocation inside the Fabric Spark runner notebook.

``run_project()`` is the single entry point ``NB_dbt_Runner_Spark`` calls. It
accepts the notebook's pipeline parameters verbatim (strings are fine, so are
the Python bools/ints an interactive user types) and owns everything after the
project zip is extracted: parameter validation, dbt argv construction, the
in-process ``dbtRunner`` call, result summaries, and the upload of dbt.log and
the run artifacts to OneLake.

dbt executes in-process on the notebook driver via dbt-fabricspark's
``method: session`` (the ``lakehouse_session`` output in the project's
profiles.yml), attaching to the notebook's own Spark session — no Livy API, no
endpoint, no credentials, nothing to tear down. dbt-fabricspark and this
package arrive together in the published bundle's ``wheels/`` folder.

``dbt`` and ``notebookutils`` are imported lazily inside the functions that
need them, so the unit tests need nothing installed.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path

VALID_COMMANDS = ("build", "run", "test", "seed", "snapshot", "compile", "docs generate")
FULL_REFRESH_COMMANDS = frozenset({"build", "run", "seed"})
VALID_LOG_LEVELS = frozenset({"debug", "info", "warn", "error", "none"})
LOCAL_DBT_LOG_DIR = "/tmp/dbt-logs"  # noqa: S108 — Fabric driver-local scratch disk
PRESERVED_ARTIFACTS = ("run_results.json", "manifest.json")
REQUIRED_PACKAGES = ("dbt-core", "dbt-fabricspark", "jaffle-dbt-runner")


# ---------------------------------------------------------------------------
# parameters -> dbt argv (pure functions, unit-tested)
# ---------------------------------------------------------------------------


def parse_bool(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def string_list(value) -> list[str]:
    """A JSON-list-in-a-string pipeline parameter as a list of strings."""
    if value in (None, ""):
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, (list, tuple)):
        raise ValueError(f"Expected a JSON list, got {type(parsed).__name__}.")
    return [str(item) for item in parsed]


def normalize_command(command) -> str:
    command = " ".join(str(command or "").split()).lower()
    if command not in VALID_COMMANDS:
        raise ValueError(f"command must be one of {list(VALID_COMMANDS)}, got {command!r}.")
    return command


def build_argv(
    command: str,
    *,
    select: str = "",
    exclude: str = "",
    full_refresh: bool = False,
    threads="",
    vars_dict: dict | None = None,
    extra_args=(),
) -> list[str]:
    """Assemble one validated dbt argv (without --project-dir/--profiles-dir).

    At most one ``--vars`` flag: dbt takes the last one it sees rather than
    merging, so everything travels in ``vars_dict``. ``extra_args`` comes last,
    which lets an operator's own flag win deliberately.
    """
    command = normalize_command(command)
    if full_refresh and command not in FULL_REFRESH_COMMANDS:
        raise ValueError(
            f"full_refresh is only valid for {sorted(FULL_REFRESH_COMMANDS)}, not {command!r}."
        )
    argv = command.split()
    if select:
        argv += ["--select", str(select)]
    if exclude:
        argv += ["--exclude", str(exclude)]
    if full_refresh:
        argv.append("--full-refresh")
    if threads not in (None, ""):
        argv += ["--threads", str(int(threads))]
    if vars_dict:
        argv += ["--vars", json.dumps(vars_dict)]
    argv += [str(arg) for arg in extra_args]
    return argv


# ---------------------------------------------------------------------------
# dbtRunner results (duck-typed, so tests use plain stubs)
# ---------------------------------------------------------------------------


def dbt_failure_detail(res) -> str:
    detail = ""
    exception = getattr(res, "exception", None)
    if exception:
        detail += f"\n  Exception: {exception}"
    result_obj = getattr(res, "result", None)
    for node_result in getattr(result_obj, "results", None) or []:
        status = str(getattr(node_result, "status", "")).lower()
        if status in {"error", "fail", "runtime error"}:
            node = getattr(node_result, "node", None)
            unique_id = getattr(node, "unique_id", "unknown")
            message = getattr(node_result, "message", "")
            detail += f"\n  {unique_id}: {status} {message}"
    return detail


def summarize_dbt_result(res) -> dict:
    node_results = getattr(getattr(res, "result", None), "results", None) or []
    status_counts: dict[str, int] = {}
    for node_result in node_results:
        status = str(getattr(node_result, "status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    return {"result_count": len(node_results), "status_counts": status_counts}


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


def load_deployment_metadata(project_dir) -> dict:
    """The deployment.json the publisher embedded next to dbt_project.yml.

    Returns an empty dict when it is missing or unreadable (a project copied
    by hand rather than published).
    """
    try:
        return json.loads((Path(project_dir) / "deployment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _log(name, value) -> None:
    print(f"{name}: {value}", flush=True)


def _export_log_levels(dbt_log_level, dbt_log_level_file) -> None:
    """Console (cell output) and file log verbosity are independent in dbt."""
    for env_name, level in (
        ("DBT_LOG_LEVEL", dbt_log_level),
        ("DBT_LOG_LEVEL_FILE", dbt_log_level_file),
    ):
        level = str(level or "").strip().lower()
        if level not in VALID_LOG_LEVELS:
            raise ValueError(f"{env_name} must be one of {sorted(VALID_LOG_LEVELS)}, got {level!r}.")
        os.environ[env_name] = level


def _upload(source: Path, destination: str, what: str) -> None:
    """Best-effort copy of a local file to OneLake; never masks the real failure."""
    if not source.is_file():
        return
    import notebookutils

    try:
        notebookutils.fs.cp(f"file:{source}", destination)
        _log(f"{what} preserved", destination)
    except Exception as exc:
        _log(f"{what} NOT preserved", exc)


def _preserve_run_artifacts(project_dir, persisted_log_root, label) -> None:
    """run_results.json + manifest.json -> <log root>/<stamp>_<label>/, per invocation."""
    if not persisted_log_root:
        return
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", label)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for name in PRESERVED_ARTIFACTS:
        _upload(
            Path(project_dir) / "target" / name,
            f"{persisted_log_root}/{stamp}_{safe_label}/{name}",
            name,
        )


def _preserve_dbt_log(persisted_log_root) -> None:
    """dbt's file log -> <log root>/dbt_<stamp>.log, once per session (finally block)."""
    if not persisted_log_root:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _upload(Path(LOCAL_DBT_LOG_DIR) / "dbt.log", f"{persisted_log_root}/dbt_{stamp}.log", "dbt log")


# ---------------------------------------------------------------------------
# dbt
# ---------------------------------------------------------------------------


def run_dbt(argv_head, project_dir, target, persisted_log_root, label) -> dict:
    """Run one dbt command in-process via the dbtRunner Python API."""
    from dbt.cli.main import dbtRunner

    argv = [
        *argv_head,
        "--project-dir", str(project_dir),
        "--profiles-dir", str(project_dir),
        "--target", target,
    ]
    print(f"\n$ dbt {' '.join(argv_head)}", flush=True)
    started = time.monotonic()
    res = dbtRunner().invoke(argv)
    elapsed = round(time.monotonic() - started, 1)

    success = bool(getattr(res, "success", False))
    summary = summarize_dbt_result(res)
    _log("Success", success)
    _log("Status counts", summary["status_counts"])
    _log("Elapsed seconds", elapsed)
    _preserve_run_artifacts(project_dir, persisted_log_root, label)
    if not success:
        raise RuntimeError(f"dbt failed for {label}:{dbt_failure_detail(res)}")
    return {
        "label": label,
        "args": list(argv_head),
        "success": success,
        "elapsed_seconds": elapsed,
        "statuses": summary["status_counts"],
    }


def run_project(
    *,
    project_dir,
    onelake_root="",
    target="lakehouse_session",
    lakehouse_name="LH_Jaffle_Shop",
    schema="jaffle_shop",
    command="build",
    select="",
    exclude="",
    full_refresh="false",
    threads="",
    load_source_data="false",
    dbt_extra_args="[]",
    dbt_log_path="Files/dbt-logs",
    dbt_log_level="info",
    dbt_log_level_file="debug",
) -> dict:
    """Run the Jaffle Shop dbt project against the notebook's Spark session.

    Validates eagerly (bad parameters fail before dbt is even imported), runs
    ``dbt deps`` only when the bundle did not vendor ``dbt_packages/``, runs the
    one-time seed when ``load_source_data`` is true, then the requested
    ``command``, and always uploads dbt's file log in a finally block.
    ``onelake_root`` is the lakehouse's abfss root, used only for the uploads
    under ``dbt_log_path``; leaving either blank disables them. Returns the
    outcome dict the notebook hands to ``notebookutils.notebook.exit``.
    """
    project_dir = Path(project_dir)
    command = normalize_command(command)
    full_refresh_flag = parse_bool(full_refresh)
    extra_args = string_list(dbt_extra_args)
    lakehouse_name = str(lakehouse_name or "").strip()
    schema = str(schema or "").strip()
    if not lakehouse_name or not schema:
        raise ValueError("lakehouse_name and schema are required.")
    if schema == lakehouse_name:
        # With method: session the adapter cannot ask the Fabric API whether the
        # lakehouse is schema-enabled; `schema != lakehouse` is what tells it to
        # render three-part names (LH_Jaffle_Shop.jaffle_shop.customers).
        raise ValueError("schema must differ from the lakehouse name (schema-enabled lakehouse).")
    _export_log_levels(dbt_log_level, dbt_log_level_file)

    def _argv(cmd, vars_dict=None, select_value=select, exclude_value=exclude):
        return build_argv(
            cmd,
            select=select_value,
            exclude=exclude_value,
            full_refresh=full_refresh_flag,
            threads=threads,
            vars_dict=vars_dict,
            extra_args=extra_args,
        )

    # Validate the main argv before touching the filesystem or importing dbt.
    main_argv = _argv(command)

    # The lakehouse_session output of profiles.yml reads these two variables.
    os.environ["DBT_LAKEHOUSE_NAME"] = lakehouse_name
    os.environ["DBT_SCHEMA"] = schema
    persisted_log_root = f"{onelake_root}/{dbt_log_path}" if onelake_root and dbt_log_path else ""
    if dbt_log_path:
        os.environ["DBT_LOG_PATH"] = LOCAL_DBT_LOG_DIR

    deployment = load_deployment_metadata(project_dir)
    commit = str(deployment.get("commit") or "").strip()
    build_version = str(deployment.get("build_version") or "").strip()

    print("=== dbt target ===", flush=True)
    _log("Connection", "in-process Spark session (dbt-fabricspark method: session)")
    _log("Target / lakehouse / schema", f"{target} / {lakehouse_name} / {schema}")
    _log("Command", " ".join(main_argv))
    _log("Project directory", project_dir)
    _log("Deployed commit", commit or "<none>")
    _log("Deployed build version", build_version or "<none>")
    _log("Log upload destination", persisted_log_root or "disabled (local only)")
    for package_name in REQUIRED_PACKAGES:
        try:
            _log(package_name, importlib_metadata.version(package_name))
        except importlib_metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                f"{package_name} is not installed. The published zip's wheels/ folder "
                "supplies it — the bootstrap cell must run before this one, and the zip "
                "must come from tools/publish_dbt_bundle.py (check deployment.json's "
                "wheel_python_version against the driver Python if pip could not install it)."
            ) from exc

    runs = []
    started = time.monotonic()
    try:
        has_packages = any(
            (project_dir / name).is_file() for name in ("packages.yml", "dependencies.yml")
        )
        if has_packages and (project_dir / "dbt_packages").is_dir():
            _log("dbt packages", "vendored in the bundle (dbt deps skipped)")
        elif has_packages:
            runs.append(run_dbt(["deps"], project_dir, target, persisted_log_root, "deps"))

        if parse_bool(load_source_data):
            runs.append(
                run_dbt(
                    _argv("seed", {"load_source_data": True}, "", ""),
                    project_dir, target, persisted_log_root, "seed",
                )
            )
        runs.append(run_dbt(main_argv, project_dir, target, persisted_log_root, command))
    finally:
        _preserve_dbt_log(persisted_log_root)

    main = runs[-1]
    return {
        "status": "ok",
        "target": target,
        "command": command,
        "select": select,
        "exclude": exclude,
        "threads": threads,
        "success": True,
        "statuses": main["statuses"],
        "elapsed_seconds": main["elapsed_seconds"],
        "total_seconds": round(time.monotonic() - started, 1),
        "deployed_commit": commit,
        "build_version": build_version,
        "runs": runs,
    }
