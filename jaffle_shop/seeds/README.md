# `seeds/` — CSVs dbt can load, standing in for ingestion

A **seed** is a CSV file in this folder that `dbt seed` loads into a table. dbt generates the
`create table` and the `insert` statements from the file's contents.

Seeds are meant for small, static, business-owned data that belongs in version control: a list of
country codes, an exchange-rate table, a mapping of employee to region. **They are not an ingestion
tool.** dbt does not extract or load data in general — that is what Fabric pipelines, Data Factory,
Fivetran or a notebook are for. dbt starts once the data has landed.

## What these seeds are doing here

This project has no real ingestion, because a conference demo cannot depend on one. So the six CSVs in
[`jaffle-data/`](jaffle-data/) play the part: they are loaded **once per engine** into a `raw` schema,
and from that moment on the project treats them exactly as it would treat tables owned by someone
else — reached only through `source()`, never through `ref()`.

| File | Rows | Columns |
| --- | ---: | --- |
| `raw_customers.csv` | 935 | `id`, `name` |
| `raw_orders.csv` | 61,948 | `id`, `customer`, `ordered_at`, `store_id`, `subtotal`, `tax_paid`, `order_total` |
| `raw_items.csv` | 90,900 | `id`, `order_id`, `sku` |
| `raw_products.csv` | 10 | `sku`, `name`, `type`, `price`, `description` |
| `raw_stores.csv` | 6 | `id`, `name`, `opened_at`, `tax_rate` |
| `raw_supplies.csv` | 65 | `id`, `name`, `cost`, `perishable`, `sku` |

At ~150,000 rows and 16 MB these are far larger than a seed should ever be — real ingestion would
deliver them. Treat their size as the demo's compromise, not as an example to follow.

## Seeds are disabled by default

This is the part worth understanding, because it shows how configuration and Jinja combine.
In [`../dbt_project.yml`](../dbt_project.yml):

```yaml
seeds:
  jaffle_shop:
    +schema: raw
    jaffle-data:
      +enabled: "{{ var('load_source_data', false) }}"
```

`+enabled: false` removes a node from the project entirely — it is not built, not tested, and not part
of the DAG. Here the flag is not hard-coded but read from a **variable** that defaults to `false`, so:

```powershell
dbt build                                                      # 48 nodes, no seeds. Data is left alone
dbt seed --vars '{"load_source_data": true}' --target warehouse  # the one-off load
```

Without this gate, every `dbt build` during the talk would re-insert 150,000 rows — three and a half
minutes on the Warehouse, and about 45 minutes on the Lakehouse over Spark. Variables are the general
mechanism for this: `var('name', default)` in any file, `--vars` on the command line, or a `vars:`
block in `dbt_project.yml`.

`+schema: raw` is what puts the loaded tables in a separate schema from the models. It works together
with [`../macros/generate_schema_name.sql`](../macros/generate_schema_name.sql), which special-cases
seeds so they land in a plain `raw` schema rather than a per-developer one — the raw layer is shared,
the way it would be if ingestion owned it.

## Column types

dbt infers a type per column from the CSV, and getting that wrong is the usual seed problem: an `id`
that looks numeric becomes an `int` and then fails to join to a `varchar` key. So the types are pinned
explicitly in `dbt_project.yml`, per seed and per column, with a Jinja expression choosing the right
type name for the engine:

```yaml
raw_customers:
  +column_types:
    id: "{{ 'string' if target.type == 'fabricspark' else 'varchar(36)' }}"
```

`string` on Spark, `varchar(36)` on T-SQL, from one line. The same pattern handles `timestamp` versus
`datetime2(6)` for `ordered_at` and `opened_at`.

## The Lakehouse exception

Seeding the Lakehouse takes about 45 minutes, because each batched `insert` is a separate Spark
statement of roughly 8 seconds. For this project the raw tables were instead created by uploading the
CSVs to the Lakehouse `Files` area and using *Load to table* — same table and column names, `raw`
schema. Details in [`../../docs/runbook.md`](../../docs/runbook.md).

Which is the more honest story anyway: loading is somebody else's job, and dbt picks up from
`source()`.

## Seeds are not in the Fabric dbt jobs

[`../../tools/sync_fabric_dbt_jobs.py`](../../tools/sync_fabric_dbt_jobs.py) copies this project into
the Fabric dbt job items but leaves this folder out — the raw tables already exist there, and 16 MB of
CSV has no business inside a job definition.
