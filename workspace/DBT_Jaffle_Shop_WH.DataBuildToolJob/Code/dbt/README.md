# The dbt project, explained

This directory is a **dbt project**. Everything dbt knows about this warehouse is in these files, and
everything in these files is plain text: SQL, YAML and Markdown, versioned in Git like application code.
That is the whole idea behind the session title — *SQL as Software*.

If you are coming from the Microsoft data stack, the quickest translation is:

| You know | dbt calls it | Notes |
| --- | --- | --- |
| A view or `SELECT INTO` script | a **model** ([`models/`](models/)) | one file, one `select`, no DDL — dbt writes the `create view` / `create table` around it |
| The dependency order in your ETL orchestrator | the **DAG** | never declared; dbt infers it from `{{ ref() }}` calls in the SQL |
| `sqlcmd` variables / SSDT publish profiles | **targets** ([`profiles.yml`](profiles.yml)) | the same models deploy to Warehouse, Lakehouse or SQL database |
| A `CHECK` constraint or a post-load validation proc | a **test** (the `.yml` next to each model) | assertions that run as `select` statements and fail the build |
| Extended properties / a data dictionary in Confluence | **descriptions** (`.yml`, `.md`) | live beside the code and are published as a documentation site |
| A stored procedure with dynamic SQL | a **macro** ([`macros/`](macros/)) | Jinja templating, compiled to SQL before anything runs |

## The one idea to take away

dbt compiles, then runs. Nothing clever happens at run time.

```
models/marts/customers.sql          you write this — a select statement with {{ ref() }} in it
        │
        │  dbt compile / dbt run — Jinja is rendered, refs become real table names
        ▼
target/compiled/.../customers.sql   plain SQL you could paste into a query window
        │
        │  wrapped in the materialization for this model (view / table / incremental)
        ▼
target/run/.../customers.sql        create table jaffle_shop.customers as (...)
        │
        ▼
the warehouse                       a table, exactly as if you had written the DDL yourself
```

Every mystery in dbt is answerable by reading `target/compiled/` — the folder is worth opening every
time something surprises you. It appears after any `dbt compile`, `dbt run` or `dbt build`, and it is
git-ignored because it is derived, never authored.

## What is in here

| Path | What dbt does with it | Configured by |
| --- | --- | --- |
| [`dbt_project.yml`](dbt_project.yml) | the only required file — it is what makes this folder a project | — |
| [`models/`](models/README.md) | every `.sql` file becomes a view or table; the `.yml` files add descriptions and tests | `model-paths` |
| [`macros/`](macros/README.md) | reusable Jinja/SQL functions, plus overrides of dbt's own internals | `macro-paths` |
| [`seeds/`](seeds/README.md) | CSV files dbt can load into tables — here they stand in for ingestion | `seed-paths` |
| [`data-tests/`](data-tests/README.md) | hand-written test queries ("singular tests") | `test-paths` |
| [`analyses/`](analyses/README.md) | SQL that dbt compiles but never runs | `analysis-paths` |
| [`snapshots/`](snapshots/README.md) | slowly-changing-dimension history tables | `snapshot-paths` |
| [`packages.yml`](packages.yml) | third-party dbt packages to download (`dbt deps`) | — |
| [`selectors.yml`](selectors.yml) | named, saved node selections | — |
| [`profiles.yml`](profiles.yml) | connection details for each target — **the only file that knows about servers** | — |
| `target/` | compiled SQL, run results, the manifest, the docs site. Generated, git-ignored. | `target-path` |
| `dbt_packages/` | packages downloaded by `dbt deps`. Generated, git-ignored. | — |
| `logs/` | `dbt.log`, one line per statement dbt sent. Generated, git-ignored. | — |

Two things are deliberately *not* here: credentials (every value in `profiles.yml` comes from an
environment variable) and any statement of *how* to build. There is no orchestration code in this
project, because the DAG is derived from the SQL itself.

## The command vocabulary

Run these from this directory, with a virtual environment active (see the repository
[README](../README.md) for the one-time setup).

| Command | What it does |
| --- | --- |
| `dbt deps` | download the packages in `packages.yml` into `dbt_packages/` |
| `dbt debug` | check the profile and open a connection — always the first thing to run |
| `dbt compile` | render Jinja to SQL in `target/compiled/`. Touches no data |
| `dbt run` | build the models (views and tables) |
| `dbt test` | run the assertions in the `.yml` files |
| `dbt build` | `run` + `test` + `seed` + `snapshot` in DAG order — **the command to use** |
| `dbt seed` | load the CSVs in `seeds/` (disabled here unless you pass a variable — see [`seeds/`](seeds/README.md)) |
| `dbt docs generate` then `dbt docs serve` | build and serve the documentation site, lineage graph included |
| `dbt ls --select +customers` | list nodes without building anything — the fastest way to learn selection syntax |
| `dbt show --inline "select ..."` | run an ad-hoc query through the profile |

`dbt build` is the important one, and the reason is ordering: it interleaves tests with models, so a
model whose upstream test failed is **skipped** rather than built on bad data. Running `dbt run` and
then `dbt test` would have loaded the bad data first and told you afterwards.

### Selecting part of the DAG

Every command above takes `--select`, and the graph operators are what make it useful:

| Selector | Means |
| --- | --- |
| `customers` | just that one model |
| `+customers` | `customers` and everything it depends on (ancestors) |
| `stg_orders+` | `stg_orders` and everything downstream of it (descendants) |
| `+orders+` | both directions |
| `staging` | everything in the `models/staging` folder |
| `tag:finance` | everything carrying that tag |
| `state:modified+` | what changed versus a previous run, and its children — how CI stays fast |

Saved selections live in [`selectors.yml`](selectors.yml) and are used as `--selector demo1`.

## Where the demos touch these files

| Demo | Files on screen | The point being made |
| --- | --- | --- |
| 1 · Build a mart | [`models/staging/__sources.yml`](models/staging/__sources.yml), [`stg_orders.sql`](models/staging/stg_orders.sql), [`marts/customers.yml`](models/marts/customers.yml) | `source()` vs `ref()`, and what `dbt build` actually emits |
| 2 · Break it on purpose | [`models/staging/stg_orders.sql`](models/staging/stg_orders.sql) | a failing test stops the DAG; the old table is still serving |
| 3 · Follow the lineage | the docs site, [`models/overview.md`](models/overview.md) | documentation and lineage as build artefacts, not a side project |
| 4 · Change the engine | [`profiles.yml`](profiles.yml), [`macros/booleans.sql`](macros/booleans.sql) | one set of models, three SQL dialects |
| 5 · SQL database | `profiles.yml` again | same again, third engine |

The full script, with expected output and recovery steps, is in [`../docs/runbook.md`](../docs/runbook.md).

## Reading order for a newcomer

1. [`models/staging/stg_customers.sql`](models/staging/stg_customers.sql) — the simplest possible model.
2. [`models/staging/stg_customers.yml`](models/staging/stg_customers.yml) — the anatomy of a model's YAML, commented line by line.
3. [`models/staging/__sources.yml`](models/staging/__sources.yml) — where data comes into the project.
4. [`models/marts/customers.sql`](models/marts/customers.sql) — a real transformation, and `ref()` between models.
5. [`dbt_project.yml`](dbt_project.yml) — the defaults that apply to everything above.
6. [`macros/cents_to_dollars.sql`](macros/cents_to_dollars.sql) — the smallest useful macro.

Each directory has its own `README.md` doing the same job for its own concept.
