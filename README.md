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
| Fabric dbt job          | `DBT_Jaffle_Shop_WH` | `DBT_Jaffle_Shop_LH` | `DBT_Jaffle_Shop_DB` |
| Fabric notebook         | `NB_dbt_Runner` with `target = "warehouse"` | `"lakehouse"` | `"sqldb"` |
| Fabric Spark notebook   |                  | `NB_dbt_Runner_Spark` (`method: session`, target `lakehouse_session`, code from a published OneLake bundle) | |

## What is where

| Path | Purpose |
| --- | --- |
| `jaffle_shop/` | the dbt project: sources, staging views, marts, tests, unit tests, macros, `profiles.yml` |
| `requirements/` | pinned Python requirements, one file per adapter, plus `tools.in` for the bundle publisher |
| `tools/` | `setup-env.ps1` (venvs), `env.example.ps1` (variables), `scenario.ps1` (Demo 2 break/reset); `publish_dbt_bundle.py` and its modules publish the OneLake bundle `NB_dbt_Runner_Spark` runs (see below) |
| `runner/` | `jaffle-dbt-runner`: the in-notebook runner package the bundle carries; unit-tested, never committed as a wheel |
| `azure-pipelines.yml` | CI: build and test every pull request in an isolated Warehouse schema; assemble the Lakehouse bundle without uploading |
| `workspace/` | Fabric workspace items synced through Git integration (Warehouse, Lakehouse, SQL database, dbt jobs, two runner notebooks) |
| `docs/runbook.md` | the demo script: commands, expected output, recovery |
| `docs/fabric-setup.md` | one-time setup: tenant settings, service principal, Azure DevOps, dbt jobs, notebook |
| `sql-as-software-getting-started-with-dbt.pptx` | the deck |

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

Switch engine by switching venv and target: `.\.venv-lakehouse\Scripts\Activate.ps1` then
`dbt build --target lakehouse`; `.\.venv-sqldb\Scripts\Activate.ps1` then `dbt build --target sqldb`.
The model files do not change.

## Fabric Spark notebook: dbt from a published OneLake bundle

`NB_dbt_Runner_Spark` runs dbt **in-process on its own Spark driver** (dbt-fabricspark `method: session`),
the way a production platform does. Fabric runs *deployed* code, not the repo, so the notebook installs
everything from one zip in the Lakehouse instead of pulling GitHub and PyPI at run time:

```powershell
.\.venv-tools\Scripts\Activate.ps1                    # created by tools\setup-env.ps1
python tools\publish_dbt_bundle.py --workspace "<workspace name or GUID>"   # -> LH_Jaffle_Shop Files/dbt/jaffle_shop.zip
python -m pytest                                      # tool + runner unit tests
python tools\publish_dbt_bundle.py --assemble-only    # what CI does: build the zip, upload nothing
```

The same three commands are VS Code tasks (`.vscode/tasks.json`): *Publish Lakehouse bundle* (prompts for the
workspace), *Assemble Lakehouse bundle (no upload)* and *Tool and runner unit tests*.

The publisher vendors `dbt_packages/` (`dbt deps`), builds a fresh `runner/` wheel, and resolves
`requirements/lakehouse.in` against Microsoft's manifest of what Fabric Runtime 2.0 already ships
(`tools/runtime_constraints/`): wheels the runtime has are pruned, and a requirement that would *replace* a
runtime package fails the publish unless `CONSTRAINT_OVERRIDES` allow-lists it with a reason (today: `protobuf`,
`opentelemetry-api`, `pathspec`). The notebook's bootstrap cell installs the result offline in seconds, never with
`%pip`. `deployment.json` inside the zip records the commit, so a Fabric run can always be matched to the code
it ran. `NB_dbt_Runner` (Python notebook, all three engines over Livy / SQL) is unchanged and still fetches the
project from GitHub. `docs/fabric-setup.md` §6b has the details.

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
