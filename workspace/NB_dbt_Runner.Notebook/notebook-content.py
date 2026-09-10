# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "jupyter",
# META     "jupyter_kernel_name": "python3.11"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# Run dbt from a Fabric Python notebook
# One small **Python** notebook (no Spark) that runs the **same** Jaffle Shop project the laptop and the
# Azure DevOps pipeline run, against any of the three Fabric engines. The dbt process runs on this
# notebook's single-node Python kernel; the SQL still executes in the engine you pick.
# 
# | `target`    | adapter          | how the notebook authenticates                                        |
# |-------------|------------------|-----------------------------------------------------------------------|
# | `warehouse` | dbt-fabric       | `authentication: notebookutils` (token from the notebook identity)     |
# | `lakehouse` | dbt-fabricspark  | `authentication: fabric_notebook`, its own Livy Spark session          |
# | `sqldb`     | dbt-sqlserver    | `ActiveDirectoryAccessToken` obtained with `notebookutils.credentials.getToken` |
# 
# Like `NB_dbt_Runner_Spark`, this notebook installs **one published bundle** from the lakehouse
# (`tools/publish_dbt_bundle.py --runner python` -> `Files/dbt/jaffle_shop_python.zip` in `LH_Jaffle_Shop`)
# instead of pulling GitHub and PyPI at run time. The zip carries the dbt project with `dbt_packages/`
# vendored, all three adapters, and *only those wheels the Python-notebook image does not already ship*,
# resolved at publish time against Microsoft's manifest of the image (`tools/runtime_constraints/`).
# Why the change: the previous version of this notebook ran `pip install -r requirements/<target>.txt`
# on the kernel. pip upgraded azure-core on disk, but the kernel had already imported the image's
# azure-core 1.29.4 for `notebookutils` before the first cell ran, and dbt-fabric's
# `from azure.core.credentials import AccessTokenInfo` failed. In a Python notebook `pip` never restarts
# the kernel. The bootstrap below installs the bundle into a private folder and **evicts the pre-imported
# modules it shadows** from `sys.modules`, so dbt imports the bundle's azure-core; nothing in the image's
# site-packages is touched.
# 
# The `%%configure` cell binds `LH_Jaffle_Shop` as the default lakehouse **by name** (bundle source, log
# destination, and the Lakehouse target's default ids). The kernel must be **Python 3.11** (notebook
# metadata); the bundle's `deployment.json.wheel_python_version` is checked by the bootstrap, which says
# so, with the fix, if it is not. The parameters cell is what a pipeline **Notebook activity** overrides.


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
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# #### Parameters
# Strings everywhere so the same values work from a pipeline (typed parameters) and from this cell
# (Python literals are accepted too). Only the connection values of the chosen `target` are used.

# PARAMETERS CELL ********************

target = "warehouse"          # warehouse | lakehouse | sqldb
command = "build"             # build | run | test | seed | snapshot | compile | docs generate
select = ""                   # optional dbt --select expression, e.g. "stg_orders+"
exclude = ""                  # optional dbt --exclude expression
full_refresh = "false"        # --full-refresh (build/run/seed only)
threads = ""                  # --threads; empty uses the profile default (4)
load_source_data = "false"    # "true" -> run the one-time `dbt seed` of the raw tables first (slow, ~45 min over Livy!)
dbt_extra_args = "[]"         # extra dbt CLI args appended verbatim, as a JSON list, e.g. '["--debug"]'
schema = "jaffle_shop"        # target schema

# Connection details (only the ones for the chosen target are used)
warehouse_host = "ujwmlees3dhelainntzwr6wnwm-mc6fdlpim2welgjzyvhtip2uzy.datawarehouse.fabric.microsoft.com"
warehouse_name = "WH_Jaffle_Shop"
lakehouse_name = "LH_Jaffle_Shop"   # also the lakehouse the bundle and the logs live in (bound by %%configure)
lakehouse_id = ""             # empty -> the default lakehouse's id
sqldb_host = "ujwmlees3dhelainntzwr6wnwm-mc6fdlpim2welgjzyvhtip2uzy.database.fabric.microsoft.com" # <xxxx>.database.fabric.microsoft.com
sqldb_name = "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"

# Published code bundle under the default lakehouse's Files/ (tools/publish_dbt_bundle.py --runner python)
bundle_zip = "dbt/jaffle_shop_python.zip"
# OneLake folder (under the default lakehouse) for dbt.log, run_results.json and manifest.json; blank disables
dbt_log_path = "Files/dbt-logs"
dbt_log_level = "info"        # cell output: debug | info | warn | error | none
dbt_log_level_file = "debug"  # file log, uploaded to <dbt_log_path> after the run

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# #### Bootstrap the published bundle
# Copies the zip from the default lakehouse to the kernel's disk and hands it to the bundle's own
# `bundle_bootstrap.py` (`tools/fabric_bundle_bootstrap.py`, shipped inside every zip): extract,
# Python-version assert, offline `pip install --no-index --no-deps --target`, `sys.path`, and - Python
# notebook only - eviction of the pre-imported modules the bundle shadows. Must run before any
# first-party import.

# CELL ********************

# --- bundle bootstrap: begin ---
import sys
from pathlib import Path

import notebookutils

ctx = notebookutils.runtime.context
if ctx.get("defaultLakehouseName", "") != lakehouse_name:
    raise ValueError(
        f"default lakehouse is {ctx.get('defaultLakehouseName')!r}; the %%configure cell must bind "
        f"{lakehouse_name} so the bundle, the logs and the Lakehouse target resolve against it"
    )
bundle_workspace_id = ctx.get("defaultLakehouseWorkspaceId") or ctx["currentWorkspaceId"]
bundle_onelake_root = (
    f"abfss://{bundle_workspace_id}@onelake.dfs.fabric.microsoft.com/{ctx['defaultLakehouseId']}"
)
bundle_zip_path = Path("/tmp") / Path(bundle_zip).name
try:
    notebookutils.fs.cp(f"{bundle_onelake_root}/Files/{bundle_zip}", f"file:{bundle_zip_path}")
except Exception as exc:
    raise FileNotFoundError(
        f"Could not fetch Files/{bundle_zip} from {lakehouse_name}: publish it with "
        "`python tools/publish_dbt_bundle.py --runner python --workspace <workspace name>` (from .venv-tools)."
    ) from exc
# zipimport: the bootstrap module runs straight from the zip, so no code has to
# exist on the kernel before it. Dropped from sys.path again once imported.
sys.modules.pop("bundle_bootstrap", None)
sys.path.insert(0, str(bundle_zip_path))
try:
    import bundle_bootstrap
finally:
    sys.path.remove(str(bundle_zip_path))
bundle = bundle_bootstrap.bootstrap(bundle_zip_path, evict_shadowed=True)
project_dir = bundle.bundle_dir
# --- bundle bootstrap: end ---

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }

# MARKDOWN ********************

# #### Run dbt
# One call. The runner validates the parameters, exports the environment variables the chosen output of
# the project's `profiles.yml` reads (and, for `sqldb`, fetches the access token), runs `dbt deps` only if
# the bundle did not vendor `dbt_packages/`, seeds first when `load_source_data` is true, and uploads
# dbt.log even when dbt fails. The outcome JSON is the notebook's exit value, so a pipeline can branch on it.

# CELL ********************

import json

from jaffle_dbt_runner import run_project

result = run_project(
    project_dir=project_dir,
    onelake_root=bundle_onelake_root,
    target=target,
    lakehouse_name=lakehouse_name,
    lakehouse_id=lakehouse_id or ctx.get("defaultLakehouseId", ""),
    workspace_id=bundle_workspace_id,
    warehouse_host=warehouse_host,
    warehouse_name=warehouse_name,
    sqldb_host=sqldb_host,
    sqldb_name=sqldb_name,
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

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "jupyter_python"
# META }
