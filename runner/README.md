# jaffle-dbt-runner

The in-notebook runner for the Jaffle Shop dbt project. Both runner notebooks
stay thin bootstraps (fetch the published bundle, call `run_project()`);
everything with behavior lives here, where `python -m pytest` can test it
without dbt or Fabric installed.

| notebook | kind | `target` (profiles.yml output) | how dbt reaches the engine |
| --- | --- | --- | --- |
| `NB_dbt_Runner_Spark` | PySpark | `lakehouse_session` | dbt-fabricspark `method: session` attaches to the notebook's own Spark session: no Livy API, no endpoint, no credentials |
| `NB_dbt_Runner` | Python (3.11 kernel) | `warehouse` | dbt-fabric, `authentication: notebookutils` |
| | | `lakehouse` | dbt-fabricspark `method: livy`, `authentication: fabric_notebook` (its own Livy session) |
| | | `sqldb` | dbt-sqlserver, `ActiveDirectoryAccessToken`; the runner fetches the token with `notebookutils.credentials.getToken` |

```python
from jaffle_dbt_runner import run_project

result = run_project(
    project_dir="/tmp/jaffle_shop_python/<commit>",       # the extracted bundle
    onelake_root="abfss://<ws>@onelake.dfs.fabric.microsoft.com/<lakehouse>",
    target="warehouse", warehouse_host="<xxx>.datawarehouse.fabric.microsoft.com", warehouse_name="WH_Jaffle_Shop",
    schema="jaffle_shop", command="build", select="+customers", threads="4",
)
notebookutils.notebook.exit(json.dumps(result))
```

What `run_project()` owns: parameter validation and dbt argv construction (one
`--vars` at most), the environment variables the chosen `profiles.yml` output
reads (`target_environment()`, pure and tested per target: `DBT_SCHEMA`,
`DBT_WAREHOUSE_HOST`/`DBT_AUTH=notebookutils`, `DBT_LAKEHOUSE_ID`/`DBT_SPARK_AUTH=fabric_notebook`,
`DBT_SQLDB_ACCESS_TOKEN`/`DBT_AUTH=ActiveDirectoryAccessToken`, ...), `dbt deps`
only when the bundle did not vendor `dbt_packages/`, the one-time `dbt seed` when
`load_source_data` is true, the in-process `dbtRunner` call with a status
summary, and the upload of `dbt.log`, `run_results.json` and `manifest.json` to
`Files/dbt-logs/` in the lakehouse (dbt.log even when dbt fails). A failed dbt
run raises, so a pipeline Notebook activity fails with it. The access token is
never printed (the run header redacts it).

## Delivery

Never published to PyPI, never committed as a wheel: `tools/publish_dbt_bundle.py`
builds this package fresh (`pip wheel --no-deps`, pure Python) into every
published zip's `wheels/` folder, alongside the part of the adapters'
dependency closure that the target Fabric runtime does not already ship
(resolved against the runtime manifests in `tools/runtime_constraints/`; see
`tools/onelake_bundle.py`). `--runner spark` builds the dbt-fabricspark-only
bundle for Runtime 2.0 (Python 3.13); `--runner python` builds the
three-adapter bundle for the Python-notebook image (Python 3.11 kernel). The
notebooks' bootstrap cell installs the bundle offline with `--no-deps` into a
private `--target` dir, so runner, project and adapters version together and
update together with one publish.

## Constraints

- Runs on a Fabric kernel's Python. `dbt` and `notebookutils` are imported
  lazily inside the functions that need them — keep it that way, so the unit
  tests need nothing installed.
- The `sqldb` token is static (dbt-sqlserver cannot refresh an
  `ActiveDirectoryAccessToken`); a run has to finish inside the token's hour.
  The full Jaffle Shop build takes about a minute there.
- `cancel()` / `rollback()` are not implemented under dbt-fabricspark's
  session method; runs are non-interactive and dbt's own scheduler still stops
  on failures the way `dbt build` always does.

This package and the bundle tooling are a port of the AANA Hub's
`aana-dbt-runner` / `scripts/onelake_bundle.py` (2026-09), trimmed to what one
project in one lakehouse needs.
