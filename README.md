# SQL as Software: Getting Started with dbt

Companion repository for the conference session of the same name: an introduction to dbt for
Microsoft data platform people (Power BI, data engineering, DBA). One dbt project, the
[dbt Labs Jaffle Shop](https://github.com/dbt-labs/jaffle-shop), built against three Fabric
engines from four different hosts.

|                         | Fabric Warehouse | Fabric Lakehouse | Fabric SQL database |
| ----------------------- | :--------------: | :--------------: | :-----------------: |
| adapter                 | `dbt-fabric`     | `dbt-fabricspark` | `dbt-sqlserver`    |
| profile target          | `warehouse`      | `lakehouse`      | `sqldb`             |
| laptop                  | Demo 1-3         | Demo 4           | Demo 5              |
| Azure DevOps pipeline   | `--target ci`    |                  |                     |
| Fabric dbt job (project synced into the item) | `DBT_Jaffle_Shop_WH` | `DBT_Jaffle_Shop_LH` | `DBT_Jaffle_Shop_DB` |
| Fabric Python notebook  | `NB_dbt_Runner` with `target = "warehouse"` (code from a published OneLake bundle) | `"lakehouse"` (Livy) | `"sqldb"` |
| Fabric Spark notebook   |                  | `NB_dbt_Runner_Spark` (`method: session`, target `lakehouse_session`, code from a published OneLake bundle) | |

## What is where

| Path | Purpose |
| --- | --- |
| `jaffle_shop/` | the dbt project: sources, staging views, marts, tests, unit tests, macros, `profiles.yml`. Documented for teaching from the inside — see below |
| `requirements/` | pinned Python requirements, one file per adapter, plus `tools.in` for the bundle publisher |
| `tools/` | `setup-env.ps1` (venvs), `env.example.ps1` (variables), `scenario.ps1` (Demo 2 break/reset); `publish_dbt_bundle.py` and its modules publish the OneLake bundles the two runner notebooks run (see below); `sync_fabric_dbt_jobs.py` copies the project into the Fabric dbt job items (`workspace/DBT_*/Code/dbt`, checked in CI) |
| `runner/` | `jaffle-dbt-runner`: the in-notebook runner package the bundles carry; unit-tested, never committed as a wheel |
| `azure-pipelines.yml` | CI: build and test every pull request in an isolated Warehouse schema; assemble both Lakehouse bundles without uploading |
| `workspace/` | Fabric workspace items synced through Git integration (Warehouse, Lakehouse, SQL database, dbt jobs with their generated `Code/dbt` copy of the project, two runner notebooks) |
| `docs/runbook.md` | the demo script: commands, expected output, recovery |
| `docs/fabric-setup.md` | one-time setup: tenant settings, service principal, Azure DevOps, dbt jobs, notebook |
| `sql-as-software-getting-started-with-dbt.pptx` | the deck |

## The project explains itself

The dbt project is documented from the inside, so it can be read on screen during the talk without
slides. Every directory has a `README.md` covering the dbt concept it holds, and the files themselves
carry teaching comments — Jinja comments in the models (stripped at compile time, so the warehouse
objects stay clean) and `#` comments in the YAML.

| Start here | Teaches |
| --- | --- |
| [`jaffle_shop/README.md`](jaffle_shop/README.md) | what a dbt project is, translated for Microsoft data platform people; the compile-then-run model; the command vocabulary |
| [`jaffle_shop/models/README.md`](jaffle_shop/models/README.md) | `source()` vs `ref()` and how the DAG is derived; the staging/marts split; materializations |
| [`jaffle_shop/models/staging/README.md`](jaffle_shop/models/staging/README.md) | why a "does nothing" layer earns its place |
| [`jaffle_shop/models/marts/README.md`](jaffle_shop/models/marts/README.md) | grain, and aggregate-before-you-join |
| [`jaffle_shop/macros/README.md`](jaffle_shop/macros/README.md) | Jinja, `adapter.dispatch`, and overriding dbt's own macros |
| [`jaffle_shop/seeds/README.md`](jaffle_shop/seeds/README.md) | what seeds are for, and what they are not |
| [`jaffle_shop/data-tests/README.md`](jaffle_shop/data-tests/README.md) | generic vs singular vs unit tests |
| [`jaffle_shop/analyses/README.md`](jaffle_shop/analyses/README.md) | compiled-but-never-run SQL |
| [`jaffle_shop/snapshots/README.md`](jaffle_shop/snapshots/README.md) | slowly-changing dimensions, and why this project has none |

Suggested reading order for someone new to dbt is at the bottom of `jaffle_shop/README.md`.
[`jaffle_shop/models/_shared__docs.md`](jaffle_shop/models/_shared__docs.md) holds the doc blocks that
several models' column descriptions pull in, which is also what the documentation site renders in
Demo 3.

## Quick start (laptop)

```powershell
winget install astral-sh.uv Microsoft.AzureCLI       # once
.\tools\setup-env.ps1                                # .venv-warehouse, .venv-lakehouse, .venv-sqldb
Copy-Item tools\env.example.ps1 tools\env.ps1         # fill in the lakehouse id and SQL database host
az login

.\.venv-warehouse\Scripts\Activate.ps1
. .\tools\env.ps1
cd jaffle_shop
dbt deps
dbt debug --target warehouse

# one-time: load the raw tables (seeds are disabled otherwise; this takes a while on the Warehouse)
dbt seed --vars '{"load_source_data": true}' --target warehouse

dbt build --target warehouse
dbt docs generate; dbt docs serve --port 8080
```

The docs site is also a set of VS Code tasks, so it takes one click during a demo — *Terminal → Run Task →*
**dbt docs: generate + serve (Warehouse)** (also the default build task, Ctrl+Shift+B). They dot-source
`tools\env.ps1` for you. **dbt docs: generate (choose engine)** does the same against the Lakehouse or SQL
database, **dbt docs: generate standalone HTML (demo fallback)** writes a single self-contained
`target\static_index.html` that needs no server or network, and **dbt: debug connection (choose engine)** is
the first thing to run when something fails. Generating queries the engine and needs `az login`; serving does
not connect at all, so a served site outlives the token.

Switch engine by switching venv and target: `.\.venv-lakehouse\Scripts\Activate.ps1` then
`dbt build --target lakehouse`; `.\.venv-sqldb\Scripts\Activate.ps1` then `dbt build --target sqldb`.
The model files do not change.

## Fabric notebooks: dbt from a published OneLake bundle

Both runner notebooks run dbt **in-process on the notebook's kernel**, the way a production platform
does: Fabric runs *deployed* code, not the repo, so each notebook installs everything from one zip in the
Lakehouse instead of pulling GitHub and PyPI at run time.

- `NB_dbt_Runner_Spark` (PySpark, Spark Runtime 2.0): dbt-fabricspark `method: session` attaches to the
  notebook's own Spark session. Bundle `Files/dbt/jaffle_shop.zip`.
- `NB_dbt_Runner` (Python, 3.11 kernel): all three engines as the notebook identity - dbt-fabric with
  `authentication: notebookutils`, dbt-fabricspark over Livy with `fabric_notebook`, dbt-sqlserver with a
  `notebookutils` access token. Bundle `Files/dbt/jaffle_shop_python.zip`.

```powershell
.\.venv-tools\Scripts\Activate.ps1                    # created by tools\setup-env.ps1
python tools\publish_dbt_bundle.py --runner spark  --workspace "<workspace name or GUID>"   # -> Files/dbt/jaffle_shop.zip
python tools\publish_dbt_bundle.py --runner python --workspace "<workspace name or GUID>"   # -> Files/dbt/jaffle_shop_python.zip
python -m pytest                                      # tool + runner unit tests
python tools\publish_dbt_bundle.py --runner python --assemble-only    # what CI does: build the zip, upload nothing
```

The same commands are VS Code tasks (`.vscode/tasks.json`): *Publish Lakehouse bundle (Spark runner)* /
*(Python runner)* (prompt for the workspace), *Assemble Lakehouse bundles (no upload)* and *Tool and runner
unit tests*.

The publisher vendors `dbt_packages/` (`dbt deps`), builds a fresh `runner/` wheel, and resolves the adapter
pins from `requirements/*.in` against Microsoft's manifest of what the target runtime already ships
(`tools/runtime_constraints/`: the Runtime 2.0 conda YML, and the Python-notebook image's release note for the
3.11 kernel). Wheels the runtime has are pruned, and a requirement that would *replace* a runtime package fails
the publish unless the runner's overrides allow-list it with a reason (Spark: `protobuf`, `opentelemetry-api`,
`pathspec`; Python: `azure-core`, `azure-identity`, `pyodbc`). The notebooks' bootstrap cell installs the
result offline in seconds, never with `%pip`; on the Python kernel it also evicts the modules the kernel had
already imported from the image (notebookutils' azure-core) so dbt gets the bundle's copies - the
`cannot import name 'AccessTokenInfo'` failure the pip-at-run-time version of the notebook hit.
`deployment.json` inside the zip records the commit, so a Fabric run can always be matched to the code it
ran. `docs/fabric-setup.md` §6 has the details.

## How the project differs from upstream

- Written in a portable SQL subset so the same files run on T-SQL and Spark SQL: explicit `group by`
  columns, and two dispatch macros (`to_bool`, `is_true`) for boolean columns next to the upstream
  `cents_to_dollars`.
- `macros/tsql_overrides.sql` fixes two adapter gaps found on Fabric: `dbt_utils.expression_is_true`
  needs a named column inside the T-SQL test wrapper, and the adapters' `date_trunc` rounds
  `23:59:59.9999` into the next day. Unit-test boolean fixtures are quoted (`"true"`) because T-SQL has
  no boolean literal.
- Seeds are gated by `var('load_source_data')` and land in a `raw` schema; models read them through
  `source('ecom', ...)`, the way a real project reads tables that ingestion owns.
- The semantic-layer YAML (semantic models, metrics, saved queries) and the time spine are removed:
  they need dbt Core 1.12 and the Fabric dbt job runtime is dbt Core 1.11.
- `profiles.yml` is committed because it contains only environment-variable references.

## Licence

MIT, see `LICENSE`. Jaffle Shop data and models are from dbt Labs under their licence.
