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

## What is where

| Path | Purpose |
| --- | --- |
| `jaffle_shop/` | the dbt project: sources, staging views, marts, tests, unit tests, macros, `profiles.yml` |
| `requirements/` | pinned Python requirements, one file per adapter |
| `tools/` | `setup-env.ps1` (venvs), `env.example.ps1` (variables), `scenario.ps1` (Demo 2 break/reset) |
| `azure-pipelines.yml` | CI: build and test every pull request in an isolated Warehouse schema |
| `workspace/` | Fabric workspace items synced through Git integration (Warehouse, Lakehouse, SQL database, dbt jobs, runner notebook) |
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

## How the project differs from upstream

- Written in a portable SQL subset so the same files run on T-SQL and Spark SQL: explicit `group by`
  columns, and two dispatch macros (`to_bool`, `is_true`) for boolean columns next to the upstream
  `cents_to_dollars`.
- Seeds are gated by `var('load_source_data')` and land in a `raw` schema; models read them through
  `source('ecom', ...)`, the way a real project reads tables that ingestion owns.
- The semantic-layer YAML (semantic models, metrics, saved queries) and the time spine are removed:
  they need dbt Core 1.12 and the Fabric dbt job runtime is dbt Core 1.11.
- `profiles.yml` is committed because it contains only environment-variable references.

## Licence

MIT, see `LICENSE`. Jaffle Shop data and models are from dbt Labs under their licence.
