# jaffle-dbt-runner

The in-notebook runner for the Jaffle Shop dbt project. `NB_dbt_Runner_Spark`
stays a thin bootstrap (fetch the published bundle, call `run_project()`);
everything with behavior lives here, where `python -m pytest` can test it
without dbt or Fabric installed.

dbt executes **in-process on the notebook's Spark driver** via dbt-fabricspark's
`method: session` (the `lakehouse_session` output of `jaffle_shop/profiles.yml`;
adapter 1.13.4 is the floor — earlier session support still called Fabric APIs a
runtime session cannot reach): the adapter attaches to the notebook's running
Spark session with `getOrCreate()`, so there is no Livy API, no endpoint, no
credentials and nothing to tear down.

```python
from jaffle_dbt_runner import run_project

result = run_project(
    project_dir="/tmp/jaffle_shop/<commit>",              # the extracted bundle
    onelake_root="abfss://<ws>@onelake.dfs.fabric.microsoft.com/<lakehouse>",
    lakehouse_name="LH_Jaffle_Shop", schema="jaffle_shop",
    command="build", select="+customers", threads="4",
)
notebookutils.notebook.exit(json.dumps(result))
```

What `run_project()` owns: parameter validation and dbt argv construction (one
`--vars` at most), the `DBT_LAKEHOUSE_NAME` / `DBT_SCHEMA` variables the profile
reads, `dbt deps` only when the bundle did not vendor `dbt_packages/`, the
one-time `dbt seed` when `load_source_data` is true, the in-process `dbtRunner`
call with a status summary, and the upload of `dbt.log`, `run_results.json` and
`manifest.json` to `Files/dbt-logs/` in the lakehouse (dbt.log even when dbt
fails). A failed dbt run raises, so a pipeline Notebook activity fails with it.

## Delivery

Never published to PyPI, never committed as a wheel: `tools/publish_dbt_bundle.py`
builds this package fresh (`pip wheel --no-deps`, pure Python) into every
published zip's `wheels/` folder, alongside the part of dbt-fabricspark's
dependency closure that Fabric Runtime 2.0 does not already ship (resolved
against the runtime manifest in `tools/runtime_constraints/`; see
`tools/onelake_bundle.py`). The notebook's bootstrap cell installs the bundle
offline with `--no-deps` into a private `--target` dir, so runner, project and
adapter version together and update together with one publish.

## Constraints

- Runs on the Fabric Spark runtime's driver Python. `dbt` and `notebookutils`
  are imported lazily inside the functions that need them — keep it that way,
  so the unit tests need nothing installed.
- `cancel()` / `rollback()` are not implemented under the adapter's session
  method; runs are non-interactive and dbt's own scheduler still stops on
  failures the way `dbt build` always does.

This package and the bundle tooling are a port of the AANA Hub's
`aana-dbt-runner` / `scripts/onelake_bundle.py` (2026-09), trimmed to what one
project in one lakehouse needs.
