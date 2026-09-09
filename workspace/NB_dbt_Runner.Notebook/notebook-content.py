# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "jupyter",
# META     "jupyter_kernel_name": "python3.11"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse_name": "LH_Jaffle_Shop",
# META       "default_lakehouse_workspace_id": "ad51bc60-66e8-45ac-9939-c54f343f54ce"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # Run dbt from a Fabric notebook
# One small Python notebook that runs the **same** Jaffle Shop project the laptop and the
# Azure DevOps pipeline run, against any of the three Fabric targets. The dbt process runs
# on this notebook's single-node Python compute; the SQL still executes in the engine you pick.
# | `target`    | adapter          | how the notebook authenticates                         |
# |-------------|------------------|--------------------------------------------------------|
# | `warehouse` | dbt-fabric       | `authentication: notebookutils` (token from the notebook identity) |
# | `lakehouse` | dbt-fabricspark  | `authentication: fabric_notebook`, its own Livy Spark session |
# | `sqldb`     | dbt-sqlserver    | `ActiveDirectoryAccessToken` obtained with `notebookutils.credentials.getToken` |
# 
# 
# The parameters cell below is what a pipeline **Notebook activity** overrides.

# PARAMETERS CELL ********************

target = "warehouse"          # warehouse | lakehouse | sqldb
command = "build"             # build | run | test | compile | docs generate
select = ""                   # optional dbt --select expression, e.g. "stg_orders+"
schema = "jaffle_shop"        # target schema
load_source_data = False      # True -> run the one-time `dbt seed` of the raw tables first (slow!)

repo_owner = "aboerger"
repo_name = "getting-started-with-dbt"
repo_ref = "main"
project_subdir = "jaffle_shop"

# Connection details (only the ones for the chosen target are used)
warehouse_host = "ujwmlees3dhelainntzwr6wnwm-mc6fdlpim2welgjzyvhtip2uzy.datawarehouse.fabric.microsoft.com"
warehouse_name = "WH_Jaffle_Shop"
lakehouse_id = ""             # empty -> the notebook's default lakehouse
lakehouse_name = "LH_Jaffle_Shop"
sqldb_host = ""               # <xxxx>.database.fabric.microsoft.com
sqldb_name = "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

# 1. Install the pinned dbt + adapter for the chosen target (same lock file as the laptop and CI)
import subprocess, sys

requirements_url = (
    f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{repo_ref}/requirements/{target}.txt"
)
print("installing", requirements_url)
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", requirements_url])
subprocess.check_call([sys.executable, "-m", "dbt.cli.main", "--version"])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

# 2. Fetch the project from GitHub (zip download, no git dependency)
import io, pathlib, shutil, urllib.request, zipfile

work = pathlib.Path("/tmp/dbt-jaffle-shop")
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)

zip_url = f"https://codeload.github.com/{repo_owner}/{repo_name}/zip/refs/heads/{repo_ref}"
with urllib.request.urlopen(zip_url) as resp:
    zipfile.ZipFile(io.BytesIO(resp.read())).extractall(work)

repo_root = next(work.glob(f"{repo_name}-*"))
project_dir = repo_root / project_subdir
print("project:", project_dir)
print(sorted(p.name for p in project_dir.iterdir()))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

# 3. Environment for profiles.yml: same variables the laptop uses, plus notebook authentication
import os, time
import notebookutils

ctx = notebookutils.runtime.context
os.environ["DBT_FABRIC_WORKSPACE_ID"] = ctx["currentWorkspaceId"]
os.environ["DBT_SCHEMA"] = schema
profiles_dir = project_dir  # the repo's profiles.yml; overridden below for sqldb only

if target == "warehouse":
    os.environ["DBT_WAREHOUSE_HOST"] = warehouse_host
    os.environ["DBT_WAREHOUSE_NAME"] = warehouse_name
    os.environ["DBT_AUTH"] = "notebookutils"          # dbt-fabric asks notebookutils for a SQL-scoped token

elif target == "lakehouse":
    os.environ["DBT_LAKEHOUSE_ID"] = lakehouse_id or ctx.get("defaultLakehouseId", "")
    os.environ["DBT_LAKEHOUSE_NAME"] = lakehouse_name or ctx.get("defaultLakehouseName", "")
    os.environ["DBT_SPARK_AUTH"] = "fabric_notebook"  # dbt-fabricspark opens a Livy session as the notebook identity
    if not os.environ["DBT_LAKEHOUSE_ID"]:
        raise ValueError("Set lakehouse_id or attach LH_Jaffle_Shop as the default lakehouse")

elif target == "sqldb":
    if not sqldb_host:
        raise ValueError("Set sqldb_host to the SQL database server name")
    os.environ["DBT_SQLDB_HOST"] = sqldb_host
    os.environ["DBT_SQLDB_NAME"] = sqldb_name
    # dbt-sqlserver has no notebookutils mode, but it accepts a ready-made Entra access token.
    token = notebookutils.credentials.getToken("https://database.windows.net/.default")
    profiles_dir = work / "profiles-sqldb"
    profiles_dir.mkdir(exist_ok=True)
    (profiles_dir / "profiles.yml").write_text(
        "jaffle_shop:\n"
        "  target: sqldb\n"
        "  outputs:\n"
        "    sqldb:\n"
        "      type: sqlserver\n"
        "      driver: 'ODBC Driver 18 for SQL Server'\n"
        f"      server: '{sqldb_host}'\n"
        "      port: 1433\n"
        f"      database: '{sqldb_name}'\n"
        f"      schema: '{schema}'\n"
        "      authentication: ActiveDirectoryAccessToken\n"
        f"      access_token: '{token}'\n"
        f"      access_token_expires_on: {int(time.time()) + 3600}\n"
        "      encrypt: true\n"
        "      trust_cert: false\n"
        "      threads: 4\n"
    )
else:
    raise ValueError(f"unknown target {target!r}")

print("target:", target, "| schema:", schema, "| profiles:", profiles_dir)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

# 4. Run dbt in-process and keep the result object
import json
from dbt.cli.main import dbtRunner

common = ["--project-dir", str(project_dir), "--profiles-dir", str(profiles_dir), "--target", target]
runner = dbtRunner()

def run(args):
    print("\n$ dbt", " ".join(args))
    res = runner.invoke(args + common)
    if res.exception:
        raise res.exception
    return res

run(["deps"])
if load_source_data:
    run(["seed", "--vars", json.dumps({"load_source_data": True})])

args = command.split()
if select:
    args += ["--select", select]
result = run(args)

statuses = {}
for r in getattr(result.result, "results", []) or []:
    statuses[str(r.status)] = statuses.get(str(r.status), 0) + 1
print("\nsummary:", statuses, "| success:", result.success)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# CELL ********************

# 5. Keep the artifacts (manifest.json, run_results.json) and hand the outcome to the caller
run_id = time.strftime("%Y%m%d-%H%M%S")
artifact_dir = pathlib.Path("/lakehouse/default/Files/dbt_artifacts") / target / run_id
try:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "run_results.json"):
        src = project_dir / "target" / name
        if src.exists():
            shutil.copy(src, artifact_dir / name)
    print("artifacts:", artifact_dir)
except OSError as exc:
    print("no default lakehouse attached, artifacts not copied:", exc)

outcome = {"target": target, "command": command, "select": select, "success": result.success, "statuses": statuses}
notebookutils.notebook.exit(json.dumps(outcome))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
