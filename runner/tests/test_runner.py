"""Runner behavior with no dbt/Fabric installed.

Pins the dbt argv the parameters produce, the fail-loud validation, the
per-target environment for profiles.yml, the deps/seed/main sequencing, and the
log-upload plumbing. ``run_dbt`` is faked on the module so no dbt import is
ever reached; env vars the runner touches are snapshotted and restored.
"""

from __future__ import annotations

import json
import os
from importlib import metadata
from types import SimpleNamespace

import pytest
from jaffle_dbt_runner import runner as runner_module
from jaffle_dbt_runner.runner import (
    TARGETS,
    build_argv,
    dbt_failure_detail,
    normalize_command,
    normalize_target,
    parse_bool,
    required_packages,
    string_list,
    summarize_dbt_result,
    target_environment,
)

ENV_KEYS = (
    "DBT_LOG_LEVEL", "DBT_LOG_LEVEL_FILE", "DBT_LOG_PATH", "DBT_SCHEMA",
    "DBT_LAKEHOUSE_NAME", "DBT_LAKEHOUSE_ID", "DBT_FABRIC_WORKSPACE_ID", "DBT_SPARK_AUTH",
    "DBT_WAREHOUSE_HOST", "DBT_WAREHOUSE_NAME", "DBT_AUTH",
    "DBT_SQLDB_HOST", "DBT_SQLDB_NAME", "DBT_SQLDB_ACCESS_TOKEN", "DBT_SQLDB_ACCESS_TOKEN_EXPIRES_ON",
)


@pytest.fixture()
def clean_env():
    snapshot = {key: os.environ.get(key) for key in ENV_KEYS}
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    yield
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    for key, value in snapshot.items():
        if value is not None:
            os.environ[key] = value


def _fake_metadata(version):
    return SimpleNamespace(version=version, PackageNotFoundError=metadata.PackageNotFoundError)


def _run_with_fakes(tmp_path, monkeypatch, **kwargs):
    calls = []
    packages_checked = []

    def fake_run_dbt(argv_head, project_dir, target, persisted_log_root, label):
        calls.append({"argv": list(argv_head), "target": target, "log_root": persisted_log_root, "label": label})
        return {"label": label, "args": list(argv_head), "success": True, "elapsed_seconds": 1.0, "statuses": {"success": 2}}

    def fake_version(name):
        packages_checked.append(name)
        return "0.0-test"

    monkeypatch.setattr(runner_module, "run_dbt", fake_run_dbt)
    monkeypatch.setattr(runner_module, "importlib_metadata", _fake_metadata(fake_version))
    result = runner_module.run_project(project_dir=tmp_path, **kwargs)
    result["_packages_checked"] = packages_checked
    return result, calls


# --- pure functions ---------------------------------------------------------


def test_parse_bool_accepts_strings_and_python_bools():
    for truthy in ("1", "true", "TRUE", " yes ", "y", True):
        assert parse_bool(truthy) is True
    for falsy in ("", "0", "false", "no", None, "banana", False):
        assert parse_bool(falsy) is False


def test_string_list_parses_json_and_defaults():
    assert string_list('["--debug", "--no-partial-parse"]') == ["--debug", "--no-partial-parse"]
    assert string_list("") == []
    assert string_list(None) == []
    with pytest.raises(ValueError, match="Expected a JSON list"):
        string_list('{"not": "a list"}')


def test_normalize_command_accepts_known_and_rejects_unknown():
    assert normalize_command(" Build ") == "build"
    assert normalize_command("docs  generate") == "docs generate"
    with pytest.raises(ValueError, match="command must be one of"):
        normalize_command("push-to-prod")


def test_normalize_target_matches_profiles_yml_outputs():
    assert normalize_target(" Warehouse ") == "warehouse"
    assert set(TARGETS) == {"lakehouse_session", "warehouse", "lakehouse", "sqldb"}
    with pytest.raises(ValueError, match="target must be one of"):
        normalize_target("ci")  # the pipeline's isolated schema is not a notebook target


def test_required_packages_names_the_adapter_per_target():
    assert required_packages("warehouse") == ("dbt-core", "dbt-fabric", "jaffle-dbt-runner")
    assert required_packages("lakehouse") == ("dbt-core", "dbt-fabricspark", "jaffle-dbt-runner")
    assert required_packages("lakehouse_session") == ("dbt-core", "dbt-fabricspark", "jaffle-dbt-runner")
    assert required_packages("sqldb") == ("dbt-core", "dbt-sqlserver", "jaffle-dbt-runner")


def test_build_argv_full_surface():
    argv = build_argv(
        "build",
        select="stg_orders+",
        exclude="tag:slow",
        full_refresh=True,
        threads=4,
        vars_dict={"load_source_data": True},
        extra_args=["--debug"],
    )
    assert argv == [
        "build",
        "--select", "stg_orders+",
        "--exclude", "tag:slow",
        "--full-refresh",
        "--threads", "4",
        "--vars", '{"load_source_data": true}',
        "--debug",
    ]


def test_build_argv_minimal_and_multiword_command():
    assert build_argv("test") == ["test"]
    assert build_argv("docs generate") == ["docs", "generate"]
    assert "--threads" not in build_argv("run", threads="")


def test_build_argv_rejects_full_refresh_off_build_run_seed():
    with pytest.raises(ValueError, match="full_refresh"):
        build_argv("test", full_refresh=True)


def test_result_summary_and_failure_detail():
    node = SimpleNamespace(unique_id="model.jaffle_shop.customers")
    results = SimpleNamespace(results=[
        SimpleNamespace(status="success", node=node, message=""),
        SimpleNamespace(status="fail", node=node, message="Got 3 results"),
    ])
    res = SimpleNamespace(success=False, result=results, exception=None)
    assert summarize_dbt_result(res) == {"result_count": 2, "status_counts": {"success": 1, "fail": 1}}
    detail = dbt_failure_detail(res)
    assert "model.jaffle_shop.customers: fail Got 3 results" in detail
    assert dbt_failure_detail(SimpleNamespace(exception=RuntimeError("boom"), result=None)) == "\n  Exception: boom"


# --- target -> profiles.yml environment ------------------------------------


def test_target_environment_lakehouse_session_needs_a_distinct_schema():
    env = target_environment("lakehouse_session", schema="jaffle_shop", lakehouse_name="LH_Jaffle_Shop")
    assert env == {"DBT_SCHEMA": "jaffle_shop", "DBT_LAKEHOUSE_NAME": "LH_Jaffle_Shop"}
    with pytest.raises(ValueError, match="schema must differ"):
        target_environment("lakehouse_session", schema="LH_X", lakehouse_name="LH_X")
    with pytest.raises(ValueError, match="lakehouse_name is required"):
        target_environment("lakehouse_session", schema="s", lakehouse_name="")


def test_target_environment_warehouse_uses_notebookutils_auth():
    env = target_environment("warehouse", schema="jaffle_shop", warehouse_host="x.datawarehouse.fabric.microsoft.com", warehouse_name="WH_Jaffle_Shop")
    assert env == {
        "DBT_SCHEMA": "jaffle_shop",
        "DBT_WAREHOUSE_HOST": "x.datawarehouse.fabric.microsoft.com",
        "DBT_WAREHOUSE_NAME": "WH_Jaffle_Shop",
        "DBT_AUTH": "notebookutils",
    }
    with pytest.raises(ValueError, match="warehouse_host is required for target 'warehouse'"):
        target_environment("warehouse", schema="s", warehouse_name="WH")


def test_target_environment_lakehouse_livy_needs_ids_and_notebook_auth():
    env = target_environment(
        "lakehouse", schema="jaffle_shop", lakehouse_name="LH_Jaffle_Shop", lakehouse_id="lh-guid", workspace_id="ws-guid",
    )
    assert env == {
        "DBT_SCHEMA": "jaffle_shop",
        "DBT_FABRIC_WORKSPACE_ID": "ws-guid",
        "DBT_LAKEHOUSE_ID": "lh-guid",
        "DBT_LAKEHOUSE_NAME": "LH_Jaffle_Shop",
        "DBT_SPARK_AUTH": "fabric_notebook",
    }
    with pytest.raises(ValueError, match="lakehouse_id is required"):
        target_environment("lakehouse", schema="s", lakehouse_name="LH", workspace_id="ws")
    # the same schema/lakehouse name is fine here: the Livy adapter asks the Fabric API
    assert target_environment("lakehouse", schema="LH", lakehouse_name="LH", lakehouse_id="a", workspace_id="b")["DBT_SCHEMA"] == "LH"


def test_target_environment_sqldb_hands_over_the_access_token():
    env = target_environment(
        "sqldb", schema="jaffle_shop", sqldb_host="srv.database.fabric.microsoft.com", sqldb_name="DB_Jaffle_Shop-guid",
        access_token=("eyJ.token", 1_800_000_000),
    )
    assert env == {
        "DBT_SCHEMA": "jaffle_shop",
        "DBT_SQLDB_HOST": "srv.database.fabric.microsoft.com",
        "DBT_SQLDB_NAME": "DB_Jaffle_Shop-guid",
        "DBT_AUTH": "ActiveDirectoryAccessToken",
        "DBT_SQLDB_ACCESS_TOKEN": "eyJ.token",
        "DBT_SQLDB_ACCESS_TOKEN_EXPIRES_ON": "1800000000",
    }
    with pytest.raises(ValueError, match="access_token is required"):
        target_environment("sqldb", schema="s", sqldb_host="h", sqldb_name="d")
    with pytest.raises(ValueError, match="sqldb_name is required"):
        target_environment("sqldb", schema="s", sqldb_host="h", access_token=("t", 1))


def test_target_environment_rejects_blank_schema_and_unknown_target():
    with pytest.raises(ValueError, match="schema is required"):
        target_environment("warehouse", schema=" ", warehouse_host="h", warehouse_name="w")
    with pytest.raises(ValueError, match="target must be one of"):
        target_environment("snowflake", schema="s")


# --- run_project ------------------------------------------------------------


def test_run_project_main_argv_env_and_outcome(tmp_path, monkeypatch, clean_env):
    (tmp_path / "deployment.json").write_text(json.dumps({"commit": "abc123def456", "build_version": "42"}), encoding="utf-8")
    result, calls = _run_with_fakes(
        tmp_path, monkeypatch,
        command="build", select="+customers", threads="4", schema="dev_andrew",
    )
    assert [c["label"] for c in calls] == ["build"]
    assert calls[0]["argv"] == ["build", "--select", "+customers", "--threads", "4"]
    assert calls[0]["target"] == "lakehouse_session"
    assert os.environ["DBT_LAKEHOUSE_NAME"] == "LH_Jaffle_Shop"
    assert os.environ["DBT_SCHEMA"] == "dev_andrew"
    assert os.environ["DBT_LOG_LEVEL"] == "info" and os.environ["DBT_LOG_LEVEL_FILE"] == "debug"
    assert result["status"] == "ok" and result["success"] is True
    assert result["target"] == "lakehouse_session"
    assert result["statuses"] == {"success": 2}
    assert result["deployed_commit"] == "abc123def456" and result["build_version"] == "42"
    assert result["_packages_checked"] == ["dbt-core", "dbt-fabricspark", "jaffle-dbt-runner"]
    del result["_packages_checked"]
    assert json.dumps(result)  # the notebook hands it to notebookutils.notebook.exit


def test_run_project_warehouse_target(tmp_path, monkeypatch, clean_env):
    result, calls = _run_with_fakes(
        tmp_path, monkeypatch,
        target="warehouse", warehouse_host="x.datawarehouse.fabric.microsoft.com", warehouse_name="WH_Jaffle_Shop",
        schema="jaffle_shop", lakehouse_name="LH_Jaffle_Shop",  # the notebook always passes its lakehouse; unused here
    )
    assert calls[0]["target"] == "warehouse"
    assert os.environ["DBT_AUTH"] == "notebookutils"
    assert os.environ["DBT_WAREHOUSE_HOST"] == "x.datawarehouse.fabric.microsoft.com"
    assert "DBT_LAKEHOUSE_NAME" not in os.environ
    assert result["_packages_checked"][1] == "dbt-fabric"
    assert result["connection"].startswith("Fabric Warehouse")


def test_run_project_lakehouse_livy_target(tmp_path, monkeypatch, clean_env):
    _, calls = _run_with_fakes(
        tmp_path, monkeypatch,
        target="lakehouse", lakehouse_name="LH_Jaffle_Shop", lakehouse_id="lh", workspace_id="ws",
    )
    assert calls[0]["target"] == "lakehouse"
    assert os.environ["DBT_SPARK_AUTH"] == "fabric_notebook"
    assert (os.environ["DBT_LAKEHOUSE_ID"], os.environ["DBT_FABRIC_WORKSPACE_ID"]) == ("lh", "ws")


def test_run_project_sqldb_fetches_a_token_and_never_prints_it(tmp_path, monkeypatch, clean_env, capsys):
    monkeypatch.setattr(runner_module, "notebook_access_token", lambda: ("secret-token-value", 1_800_000_000))
    result, calls = _run_with_fakes(
        tmp_path, monkeypatch,
        target="sqldb", sqldb_host="srv.database.fabric.microsoft.com", sqldb_name="DB_Jaffle_Shop-guid",
    )
    assert calls[0]["target"] == "sqldb"
    assert os.environ["DBT_AUTH"] == "ActiveDirectoryAccessToken"
    assert os.environ["DBT_SQLDB_ACCESS_TOKEN"] == "secret-token-value"
    assert os.environ["DBT_SQLDB_ACCESS_TOKEN_EXPIRES_ON"] == "1800000000"
    assert result["_packages_checked"][1] == "dbt-sqlserver"
    out = capsys.readouterr().out
    assert "secret-token-value" not in out and "<redacted>" in out


def test_run_project_sqldb_validates_parameters_before_asking_for_a_token(tmp_path, monkeypatch, clean_env):
    monkeypatch.setattr(runner_module, "notebook_access_token", lambda: pytest.fail("token fetched for invalid parameters"))
    with pytest.raises(ValueError, match="sqldb_host is required"):
        runner_module.run_project(project_dir=tmp_path, target="sqldb", sqldb_name="DB")


def test_run_project_seed_first_when_load_source_data(tmp_path, monkeypatch, clean_env):
    _, calls = _run_with_fakes(tmp_path, monkeypatch, load_source_data="true", select="customers", threads=2)
    assert [c["label"] for c in calls] == ["seed", "build"]
    seed = calls[0]["argv"]
    assert seed[:1] == ["seed"] and "--select" not in seed  # the seed ignores the model selection
    assert json.loads(seed[seed.index("--vars") + 1]) == {"load_source_data": True}
    assert calls[1]["argv"] == ["build", "--select", "customers", "--threads", "2"]


def test_run_project_runs_deps_only_when_packages_are_not_vendored(tmp_path, monkeypatch, clean_env):
    (tmp_path / "packages.yml").write_text("packages: []\n", encoding="utf-8")
    _, calls = _run_with_fakes(tmp_path, monkeypatch)
    assert [c["label"] for c in calls] == ["deps", "build"]

    (tmp_path / "dbt_packages").mkdir()
    _, calls = _run_with_fakes(tmp_path, monkeypatch)
    assert [c["label"] for c in calls] == ["build"]


def test_run_project_rejects_bad_parameters_before_dbt(tmp_path, clean_env):
    # No fakes installed: reaching run_dbt (which imports dbt) would blow up.
    with pytest.raises(ValueError, match="command"):
        runner_module.run_project(project_dir=tmp_path, command="deploy")
    with pytest.raises(ValueError, match="target must be one of"):
        runner_module.run_project(project_dir=tmp_path, target="ci")
    with pytest.raises(ValueError, match="schema must differ"):
        runner_module.run_project(project_dir=tmp_path, lakehouse_name="LH_X", schema="LH_X")
    with pytest.raises(ValueError, match="warehouse_host is required"):
        runner_module.run_project(project_dir=tmp_path, target="warehouse", warehouse_name="WH")
    with pytest.raises(ValueError, match="full_refresh"):
        runner_module.run_project(project_dir=tmp_path, command="test", full_refresh="true")
    with pytest.raises(ValueError, match="DBT_LOG_LEVEL"):
        runner_module.run_project(project_dir=tmp_path, dbt_log_level="loud")


def test_run_project_log_upload_plumbing(tmp_path, monkeypatch, clean_env):
    _, calls = _run_with_fakes(
        tmp_path, monkeypatch,
        onelake_root="abfss://ws@onelake.dfs.fabric.microsoft.com/lh", dbt_log_path="Files/dbt-logs",
    )
    assert calls[0]["log_root"] == "abfss://ws@onelake.dfs.fabric.microsoft.com/lh/Files/dbt-logs"
    assert os.environ["DBT_LOG_PATH"] == runner_module.LOCAL_DBT_LOG_DIR

    _, calls = _run_with_fakes(tmp_path, monkeypatch)
    assert calls[0]["log_root"] == ""


def test_run_project_names_the_missing_package(tmp_path, monkeypatch, clean_env):
    def absent(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(runner_module, "importlib_metadata", _fake_metadata(absent))
    monkeypatch.setattr(runner_module, "run_dbt", lambda *a, **k: pytest.fail("run_dbt ran without dbt"))
    with pytest.raises(RuntimeError, match="dbt-core is not installed"):
        runner_module.run_project(project_dir=tmp_path)


def test_run_project_uploads_dbt_log_even_when_dbt_fails(tmp_path, monkeypatch, clean_env):
    preserved = []
    monkeypatch.setattr(runner_module, "importlib_metadata", _fake_metadata(lambda name: "0.0-test"))
    monkeypatch.setattr(runner_module, "_preserve_dbt_log", lambda root: preserved.append(root))

    def failing_run_dbt(*args, **kwargs):
        raise RuntimeError("dbt failed for build")

    monkeypatch.setattr(runner_module, "run_dbt", failing_run_dbt)
    with pytest.raises(RuntimeError, match="dbt failed"):
        runner_module.run_project(project_dir=tmp_path, onelake_root="abfss://x/y")
    assert preserved == ["abfss://x/y/Files/dbt-logs"]
