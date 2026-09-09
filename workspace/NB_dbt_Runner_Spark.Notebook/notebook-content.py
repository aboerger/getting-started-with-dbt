# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse_name": "LH_Jaffle_Shop",
# META       "default_lakehouse_workspace_id": "ad51bc60-66e8-45ac-9939-c54f343f54ce"
# META     }
# META   }
# META }

# MARKDOWN ********************

# # Run dbt inside this notebook's Spark session
# # The second runner notebook, for the **Lakehouse only**. `NB_dbt_Runner` (Python notebook) drives
# dbt-fabricspark over the Livy REST API, which means a separate Spark session, a ~70 s session start
# and one HTTP round trip per statement. This notebook is a **PySpark** notebook, so a Spark session
# already exists when the first cell runs. dbt-fabricspark's `method: session` attaches to it with
# `SparkSession.builder.getOrCreate()` and every dbt statement becomes a plain `spark.sql(...)` call
# on the same driver:
# # | | `NB_dbt_Runner` (`lakehouse`) | `NB_dbt_Runner_Spark` (`lakehouse_session`) |
# |---|---|---|
# | notebook kind | Python | PySpark |
# | connection | Livy API, its own Spark session | this notebook's Spark session |
# | credentials | notebook identity (`fabric_notebook`) | none: the session is already authorised |
# | profile needs | workspace id, lakehouse id, endpoint | lakehouse name and schema only |
# | where it also runs | laptop, CI, benchmarks | Fabric Spark notebooks only (needs PySpark) |
# # The Livy runner is still the one to use from a laptop and for timing comparisons; this one is
# what you schedule from a Data Factory pipeline when the Spark capacity is already paid for.
# # The default lakehouse **must** be `LH_Jaffle_Shop`: with `method: session` the adapter cannot call
# the Fabric REST API, so it reads `schema != lakehouse` in the profile as "schema-enabled lakehouse"
# and renders three-part names such as `LH_Jaffle_Shop.jaffle_shop.customers` against the session's
# default catalog.

# PARAMETERS CELL ********************

command = "build"             # build | run | test | compile | docs generate
select = ""                   # optional dbt --select expression, e.g. "+customers"
schema = "jaffle_shop"        # target schema inside the lakehouse (must differ from the lakehouse name)
lakehouse_name = "LH_Jaffle_Shop"
threads = 4                   # dbt threads; each one submits Spark jobs to the shared session
load_source_data = False      # True -> run the one-time `dbt seed` of the raw tables first (slow!)

repo_owner = "aboerger"
repo_name = "getting-started-with-dbt"
repo_ref = "main"
project_subdir = "jaffle_shop"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 1. Install dbt + dbt-fabricspark on the driver. Only the two top-level pins from requirements/lakehouse.in:
#    the fully resolved lock file is for clean venvs and would fight the Spark runtime's preinstalled packages.
#    PySpark itself is not installed; the runtime already provides it, which is all the session method needs.
import subprocess, sys

requirements_url = (
    f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{repo_ref}/requirements/lakehouse.in"
)
print("installing", requirements_url)
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", requirements_url])
subprocess.check_call([sys.executable, "-m", "dbt.cli.main", "--version"])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
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
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 3. Check the Spark session dbt is about to reuse, then set the two variables the
#    `lakehouse_session` output of the repo's profiles.yml reads. No credentials, ids or endpoint:
#    SparkSession.builder.getOrCreate() inside dbt returns this very session.
import os
import notebookutils

ctx = notebookutils.runtime.context
default_lakehouse = ctx.get("defaultLakehouseName", "")
if default_lakehouse != lakehouse_name:
    raise ValueError(
        f"default lakehouse is {default_lakehouse!r}; attach {lakehouse_name} as the default lakehouse "
        "so three-part names resolve against it"
    )
if schema == lakehouse_name:
    raise ValueError("schema must differ from the lakehouse name (schema-enabled lakehouse)")

print("spark", spark.version, "| app:", spark.sparkContext.appName, "| default lakehouse:", default_lakehouse)
print("schemas:", [r[0] for r in spark.sql(f"show schemas in {lakehouse_name}").collect()])

os.environ["DBT_LAKEHOUSE_NAME"] = lakehouse_name
os.environ["DBT_SCHEMA"] = schema
target = "lakehouse_session"
print("target:", target, "| schema:", schema, "| threads:", threads)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 4. Run dbt in-process. Same dbtRunner pattern as NB_dbt_Runner; the SQL runs as spark.sql() here.
import json, time
from dbt.cli.main import dbtRunner

common = ["--project-dir", str(project_dir), "--profiles-dir", str(project_dir), "--target", target]
runner = dbtRunner()

def run(args):
    print("\n$ dbt", " ".join(args))
    res = runner.invoke(args + common)
    if res.exception:
        raise res.exception
    return res

run(["deps"])
if load_source_data:
    run(["seed", "--threads", str(threads), "--vars", json.dumps({"load_source_data": True})])

args = command.split() + ["--threads", str(threads)]
if select:
    args += ["--select", select]
started = time.time()
result = run(args)
elapsed = round(time.time() - started, 1)

statuses = {}
for r in getattr(result.result, "results", []) or []:
    statuses[str(r.status)] = statuses.get(str(r.status), 0) + 1
print(f"\nsummary: {statuses} | success: {result.success} | {elapsed} s")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
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
    print("artifacts not copied:", exc)

outcome = {
    "target": target,
    "command": command,
    "select": select,
    "threads": threads,
    "elapsed_seconds": elapsed,
    "success": result.success,
    "statuses": statuses,
}
notebookutils.notebook.exit(json.dumps(outcome))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
