# `models/staging/` — one model per source table

The staging layer is the project's front door. Its job is to take a table exactly as ingestion
delivered it and hand the rest of the project something predictable.

**The rules this layer follows** (dbt does not enforce them; every mature project adopts something like
them):

1. One staging model per source table, named `stg_<entity>`.
2. One row out per row in — no joins, no `group by`, no filtering.
3. Only these operations: rename columns, cast types, and simple derivations of a single field.
4. Materialized as a **view**, so it costs nothing to store and is never stale.
5. Nothing downstream reads a source directly. Staging is the only layer that calls `source()`.

## Why bother with a layer that "does nothing"

It is the seam that absorbs change.

`raw_orders` has columns called `customer`, `subtotal` and `store_id`, with money in integer cents.
[`stg_orders.sql`](stg_orders.sql) renames them to `customer_id`, `subtotal_cents` and `location_id`,
and adds dollar versions. Eleven models downstream depend on those names. When ingestion renames a raw
column — and it will — exactly one file in this project changes.

It also gives every model downstream the same guarantees: consistent key names (`customer_id` means the
same thing in every model), consistent money units, consistent timestamp precision. Those guarantees
are what let `orders.sql` join four models together without defensive `coalesce` and `cast` calls.

## What is here

| Model | Source table | Beyond renaming |
| --- | --- | --- |
| [`stg_customers`](stg_customers.sql) | `raw_customers` | nothing — the minimal example |
| [`stg_orders`](stg_orders.sql) | `raw_orders` | cents to dollars (keeping both), timestamp truncated to the day |
| [`stg_order_items`](stg_order_items.sql) | `raw_items` | nothing |
| [`stg_products`](stg_products.sql) | `raw_products` | price conversion, two boolean flags derived from `type` |
| [`stg_supplies`](stg_supplies.sql) | `raw_supplies` | cost conversion, and a surrogate key built from two columns |
| [`stg_locations`](stg_locations.sql) | `raw_stores` | `opened_at` truncated to a date |

Note `raw_stores` becoming `stg_locations`: the staging layer is also where you stop using the source
system's vocabulary and start using the business's.

## The files that are not models

| File | What it is |
| --- | --- |
| [`__sources.yml`](__sources.yml) | declares the six raw tables so that `source()` can resolve them. The project's contract with ingestion |
| `stg_*.yml` | one per model: descriptions, tests, and — on `stg_locations` — a unit test |

[`stg_customers.yml`](stg_customers.yml) is commented as a walkthrough of what every one of these
files can contain; start there.

## The CTE shape

Every model in this folder is written the same way:

```sql
with

source as (

    select * from {{ source('ecom', 'raw_customers') }}

),

renamed as (

    select
        ----------  ids
        id as customer_id,
        ---------- text
        name as customer_name
    from source

)

select * from renamed
```

Two named CTEs — `source` then `renamed` — a comment banner per column group, and a final
`select *`. Nobody needs `with source as (select * from ...)`; it exists so that every staging model
in every dbt project on earth looks the same, which makes them reviewable at a glance. The final
`select * from renamed` means you can change the last CTE's name in one place while experimenting.

The comment banners (`---------- ids`, `---------- numerics`, `---------- booleans`) group columns by
type. They survive into the compiled SQL — take a look at
`target/compiled/jaffle_shop/models/staging/stg_orders.sql` after a build.

## Portability lives here

These models run on T-SQL (Fabric Warehouse, Fabric SQL database) *and* Spark SQL (Fabric Lakehouse)
from the same source files. Where the dialects genuinely differ, the difference is hidden behind a
macro instead of being duplicated:

| In the model | Why |
| --- | --- |
| `{{ cents_to_dollars('subtotal') }}` | `decimal` vs `numeric` type names |
| `{{ to_bool("type = 'jaffle'") }}` | T-SQL has no boolean type, Spark does |
| `{{ dbt.date_trunc('day', 'ordered_at') }}` | dbt ships a cross-database implementation of the function |

See [`../../macros/README.md`](../../macros/README.md) for how a macro picks the right SQL per engine.
This is the payoff shown in Demo 4: the engine changes, these files do not.
