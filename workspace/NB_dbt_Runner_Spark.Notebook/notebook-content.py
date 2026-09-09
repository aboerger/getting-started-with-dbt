# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # Run dbt inside this notebook's Spark session
#
# The Lakehouse-only runner, and the way a production platform runs dbt on Fabric (this is the
# pattern the AANA Hub's Gold layer runs on). `NB_dbt_Runner` (Python notebook) drives
# dbt-fabricspark over the Livy REST API: a separate Spark session, a ~70 s session start and one
# HTTP round trip per statement. This notebook is a **PySpark** notebook, so a Spark session already
# exists when the first cell runs; dbt-fabricspark's `method: session` attaches to it with
# `SparkSession.builder.getOrCreate()` and every dbt statement becomes a plain `spark.sql(...)` call
# on the same driver. Three things make it production-grade rather than a demo trick:
#
# 1. **Everything arrives in one published bundle.** `tools/publish_dbt_bundle.py` zips the dbt project
#    (with `dbt_packages/` vendored), a fresh `jaffle-dbt-runner` wheel, and *only those wheels of
#    dbt-fabricspark's dependency closure that the Fabric runtime does not already ship*, and uploads
#    it to `Files/dbt/jaffle_shop.zip` in `LH_Jaffle_Shop`. The zip's `deployment.json` records the
#    commit it was built from.
# 2. **Nothing is resolved at run time.** The bootstrap cell copies the zip to the driver and installs
#    `wheels/` offline (`pip --no-index --no-deps --target`, never `%pip`), in seconds. The publish
#    step resolved the closure against Microsoft's manifest of the runtime's preinstalled packages, so
#    a bundle can never silently replace a runtime package — the failure that killed sessions when
#    plain `pip install` on the driver upgraded `protobuf` past what Runtime 2.0 tolerates.
# 3. **The notebook has no logic.** It bootstraps the bundle and calls `jaffle_dbt_runner.run_project()`;
#    parameter validation, argv construction, the in-process `dbtRunner` call and the dbt.log /
#    run_results.json upload live in `runner/`, where `pytest` covers them.
#
# | | `NB_dbt_Runner` (`lakehouse`) | `NB_dbt_Runner_Spark` (`lakehouse_session`) |
# |---|---|---|
# | notebook kind | Python | PySpark |
# | connection | Livy API, its own Spark session | this notebook's Spark session |
# | code and dbt stack | GitHub zip + `pip install` from PyPI at run time | one published OneLake bundle, installed offline |
# | credentials | notebook identity (`fabric_notebook`) | none: the session is already authorised |
# | profile needs | workspace id, lakehouse id, endpoint | lakehouse name and schema only |
# | where it also runs | laptop, CI, benchmarks | Fabric Spark notebooks only (needs PySpark) |
#
# The `%%configure` cell binds `LH_Jaffle_Shop` as the default lakehouse **by name**, so the notebook
# is correct in any workspace that holds a lakehouse of that name. With `method: session` the adapter
# cannot call the Fabric REST API, so it reads `schema != lakehouse` in the profile as "schema-enabled
# lakehouse" and renders three-part names such as `LH_Jaffle_Shop.jaffle_shop.customers`.
#
# The workspace's Spark runtime must be the one the bundle was built for (Runtime 2.0, Python 3.13 -
# `deployment.json.wheel_python_version`); the bootstrap says so, with the fix, if it is not.

# CELL ********************

# MAGIC %%configure -f
# MAGIC {
# MAGIC     "defaultLakehouse": {
# MAGIC         "name": "LH_Jaffle_Shop"
# MAGIC     }
# MAGIC }

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# #### Parameters
# What a pipeline **Notebook activity** overrides. Strings everywhere so the same values work from a
# pipeline (typed parameters) and from this cell (Python literals are accepted too).

# PARAMETERS CELL ********************

command = "build"             # build | run | test | seed | snapshot | compile | docs generate
select = ""                   # optional dbt --select expression, e.g. "+customers"
exclude = ""                  # optional dbt --exclude expression
full_refresh = "false"        # --full-refresh (build/run/seed only)
threads = ""                  # --threads; empty uses the profile default (4). Each thread submits Spark jobs to this session.
load_source_data = "false"    # "true" -> run the one-time `dbt seed` of the raw tables first (slow!)
dbt_extra_args = "[]"         # extra dbt CLI args appended verbatim, as a JSON list, e.g. '["--debug"]'
schema = "jaffle_shop"        # target schema inside the lakehouse (must differ from the lakehouse name)
lakehouse_name = "LH_Jaffle_Shop"
# Published code bundle under the default lakehouse's Files/ (tools/publish_dbt_bundle.py)
bundle_zip = "dbt/jaffle_shop.zip"
# OneLake folder (under the default lakehouse) for dbt.log, run_results.json and manifest.json; blank disables
dbt_log_path = "Files/dbt-logs"
dbt_log_level = "info"        # cell output: debug | info | warn | error | none
dbt_log_level_file = "debug"  # file log, uploaded to <dbt_log_path> after the run

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# #### Bootstrap the published bundle
# Copies the zip from the default lakehouse to the driver and hands it to the bundle's own
# `bundle_bootstrap.py` (`tools/fabric_bundle_bootstrap.py`, shipped inside every zip): extract,
# Python-version assert, offline `pip install --no-index --no-deps --target`, `sys.path`. Must run before
# any first-party import.

# CELL ********************

# --- bundle bootstrap: begin ---
import sys
from pathlib import Path

import notebookutils

ctx = notebookutils.runtime.context
if ctx.get("defaultLakehouseName", "") != lakehouse_name:
    raise ValueError(
        f"default lakehouse is {ctx.get('defaultLakehouseName')!r}; the %%configure cell must bind "
        f"{lakehouse_name} so the bundle and three-part relation names resolve against it"
    )
bundle_onelake_root = (
    f"abfss://{ctx.get('defaultLakehouseWorkspaceId') or ctx['currentWorkspaceId']}"
    f"@onelake.dfs.fabric.microsoft.com/{ctx['defaultLakehouseId']}"
)
bundle_zip_path = Path("/tmp") / Path(bundle_zip).name
try:
    notebookutils.fs.cp(f"{bundle_onelake_root}/Files/{bundle_zip}", f"file:{bundle_zip_path}")
except Exception as exc:
    raise FileNotFoundError(
        f"Could not fetch Files/{bundle_zip} from {lakehouse_name}: publish it with "
        "`python tools/publish_dbt_bundle.py --workspace <workspace name>` (from .venv-tools)."
    ) from exc
# zipimport: the bootstrap module runs straight from the zip, so no code has to
# exist on the driver before it. Dropped from sys.path again once imported.
sys.modules.pop("bundle_bootstrap", None)
sys.path.insert(0, str(bundle_zip_path))
try:
    import bundle_bootstrap
finally:
    sys.path.remove(str(bundle_zip_path))
bundle = bundle_bootstrap.bootstrap(bundle_zip_path)
project_dir = bundle.bundle_dir
# --- bundle bootstrap: end ---

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# #### Run dbt
# One call. The runner exports `DBT_LAKEHOUSE_NAME` / `DBT_SCHEMA` for the `lakehouse_session` output
# of the project's `profiles.yml`, runs `dbt deps` only if the bundle did not vendor `dbt_packages/`,
# seeds first when `load_source_data` is true, and uploads dbt.log even when dbt fails. The outcome
# JSON is the notebook's exit value, so a pipeline can branch on it.

# CELL ********************

import json

from jaffle_dbt_runner import run_project

result = run_project(
    project_dir=project_dir,
    onelake_root=bundle_onelake_root,
    lakehouse_name=lakehouse_name,
    schema=schema,
    command=command,
    select=select,
    exclude=exclude,
    full_refresh=full_refresh,
    threads=threads,
    load_source_data=load_source_data,
    dbt_extra_args=dbt_extra_args,
    dbt_log_path=dbt_log_path,
    dbt_log_level=dbt_log_level,
    dbt_log_level_file=dbt_log_level_file,
)
print(json.dumps(result, indent=2))
notebookutils.notebook.exit(json.dumps(result))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
