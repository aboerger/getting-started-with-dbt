# `models/` — the transformations

A **model** is one `.sql` file containing one `select` statement. That is the entire contract.

dbt supplies everything around it: the `create view` or `create table` wrapper, the schema, the
dependency order, and the tests. You never write DDL, you never write `DROP`, and you never write
`INSERT`. You describe the shape of the result you want and dbt works out how to materialise it.

```sql
-- models/staging/stg_customers.sql, in full:
with source as (
    select * from {{ source('ecom', 'raw_customers') }}
),
renamed as (
    select id as customer_id, name as customer_name from source
)
select * from renamed
```

That file is a view called `stg_customers` in the target schema. Nothing else is needed to deploy it.

## The two functions that build the DAG

Almost all of dbt's value comes from two Jinja functions that appear where a table name would go.

| Function | Points at | Renders as | Meaning |
| --- | --- | --- | --- |
| `{{ source('ecom', 'raw_orders') }}` | a table declared in [`staging/__sources.yml`](staging/__sources.yml) | `raw.raw_orders` | data someone else owns and loads; the project's boundary |
| `{{ ref('stg_orders') }}` | another model in this project | `jaffle_shop.stg_orders` | an edge in the dependency graph |

Because dbt reads these calls out of the SQL, **the dependency graph is never written down by hand**.
Add a `ref()` and the graph changes; delete one and it changes back. It cannot drift out of date, which
is the failure mode of every hand-maintained orchestration schedule.

They also make environments free. `ref('stg_orders')` renders as whatever schema and database the
current target points to, so the same file builds in your development schema, in a CI schema, and in
production, with no find-and-replace.

## Layers

Models are organised into two layers. dbt does not enforce this — it is convention, and it is the
convention worth copying.

```
sources (raw schema, loaded by "ingestion")
   │
   ▼
staging/    stg_customers, stg_orders, stg_products, ...      views      one per source table
   │                                                                     rename, cast, no business logic
   ▼
marts/      customers, orders, order_items, products, ...     tables     joins, aggregation, business rules
   │
   ▼
Power BI, ad-hoc SQL, notebooks
```

- **[`staging/`](staging/README.md)** is a clean-up layer: one model per source table, one row per source
  row, renaming columns and fixing types. Every other model reads staging, never a source directly.
- **[`marts/`](marts/README.md)** is what the business consumes: joined, aggregated, named in business
  terms, and materialised as tables so queries are fast.

The reason for the split is that it localises change. When the raw `raw_orders.customer` column is
renamed upstream, exactly one file changes — `stg_orders.sql` — and the eleven models downstream of it
carry on unchanged.

## `.sql` and `.yml` come in pairs

Each model here has a `.yml` file beside it holding the things that are not SQL:

```
models/marts/
    customers.sql     the select statement — what the table is
    customers.yml     descriptions, tests, and configuration — what the table means and must be true of it
```

The YAML is not decoration. `description` fields become the documentation site (Demo 3), and
`data_tests` entries become real `select` statements that fail the build when they return rows
(Demo 2). Splitting them this way means a reviewer reads the logic in the `.sql` and the guarantees in
the `.yml`.

Files starting with `_` or `__` are not models — dbt only treats `.sql` files as models. The
`__sources.yml` and `_shared__docs.md` naming is a common convention that simply sorts them to the top
of the folder listing.

## Materialization: how a model becomes an object

A model's **materialization** is the strategy dbt uses to persist it. It is configuration, not code,
so changing it never changes the `select` statement.

| Materialization | dbt emits | Used here for |
| --- | --- | --- |
| `view` | `create view` | staging — cheap to build, always current, no storage |
| `table` | `create table as select` | marts — fast to query, rebuilt from scratch each run |
| `incremental` | `create` once, then `insert`/`merge` new rows | not used here; the answer when a full rebuild gets too slow |
| `ephemeral` | nothing — the SQL is inlined into its children as a CTE | not used here |

The defaults are set once, per folder, in [`../dbt_project.yml`](../dbt_project.yml):

```yaml
models:
  jaffle_shop:
    staging:
      +materialized: view
    marts:
      +materialized: table
```

Note what this makes possible: switching every mart to `incremental`, or every staging view to a table,
is a two-line change in one file. Configuration in dbt cascades from `dbt_project.yml` (whole folders)
to the `.yml` file (one model) to a `config()` block inside the SQL (most specific wins).

## Documentation lives here too

- [`overview.md`](overview.md) is the landing page of the generated documentation site.
- [`_shared__docs.md`](_shared__docs.md) holds **doc blocks**: reusable chunks of Markdown that `.yml`
  descriptions pull in by name, so one explanation can be attached to a column in several models.

Markdown files under `models/` are parsed by dbt, which is why they can hold doc blocks — and also why
a Jinja tag written loose in the prose of one of these files will fail `dbt parse`.

## Try it

```powershell
dbt ls --select +customers --resource-type model    # what customers depends on
dbt compile --select stg_orders                     # then read target/compiled/.../stg_orders.sql
dbt build --select +customers                        # build that branch and test it
```
