# `models/marts/` — what the business actually queries

Marts are the models people outside the data team use: the ones a Power BI dataset imports, an analyst
joins to, or a stakeholder queries directly. Staging is plumbing; this is the product.

Where staging models are defined by their source table, **a mart is defined by its grain** — the thing
one row represents. Say it out loud before writing any SQL:

| Model | One row is | Kind |
| --- | --- | --- |
| [`customers`](customers.sql) | one customer, with lifetime totals | fact-like summary |
| [`orders`](orders.sql) | one order, with item counts and cost | fact |
| [`order_items`](order_items.sql) | one item within an order | fact, the finest grain here |
| [`products`](products.sql) | one product (SKU) | dimension |
| [`locations`](locations.sql) | one store | dimension |
| [`supplies`](supplies.sql) | one supply-and-product combination | dimension |

Each grain is stated in the model's `.yml` description, and then *enforced* by a `unique` and
`not_null` test on the key column. That pairing — a claim in the description and a test that proves it
— is the habit to steal from this project.

## Materialized as tables

`+materialized: table` in [`../../dbt_project.yml`](../../dbt_project.yml) applies to this whole
folder, so each model here is a `create table as select`, rebuilt from scratch on every run.

Rebuilding is a deliberate default. It means the table is always exactly what the code says it is —
there is no accumulated state, no drift, and no "we think this row was loaded during the incident."
A full rebuild of all 12 models takes about 30 seconds on the Fabric Warehouse. When that stops being
true, the answer is the `incremental` materialization, which is a config change rather than a rewrite.

## The dependency chain

Marts are allowed to depend on other marts, and here they do:

```
stg_order_items ─┐
stg_orders ──────┼──▶ order_items ──▶ orders ──▶ customers
stg_products ────┤                       ▲
stg_supplies ────┘                       │
stg_customers ───────────────────────────┘   (customers also reads stg_customers)

stg_products  ──▶ products      stg_locations ──▶ locations      stg_supplies ──▶ supplies
```

Read it from the right: `customers` needs lifetime spend, which needs order totals, which need item
prices. Each step aggregates the grain one level coarser, and each step is a model you can query,
test, and document on its own — rather than one 300-line query with six nested subqueries.

`products`, `locations` and `supplies` are one-line pass-throughs of their staging views. They exist
because a mart is a *published interface*: consumers point at `products`, and if a dimension later
needs enrichment, that happens without anyone changing their reports.

## Aggregation, then join

`customers.sql`, `orders.sql` and `order_items.sql` all use the same pattern, and it is the one that
prevents the most common warehouse bug:

```sql
order_items_summary as (          -- 1. aggregate to the grain you are about to join to
    select order_id, sum(supply_cost) as order_cost
    from order_items
    group by order_id
),
compute_booleans as (             -- 2. then join one row to one row
    select orders.*, order_items_summary.order_cost
    from orders
    left join order_items_summary on orders.order_id = order_items_summary.order_id
)
```

Joining the detail table directly would fan out one order into several rows and silently double every
sum. Collapsing to the target grain *first* makes the join safe. The unit test
`test_supply_costs_sum_correctly` in [`order_items.yml`](order_items.yml) exists precisely to pin this
behaviour down — it feeds two supply rows for one product and asserts the cost is summed, not
duplicated.

## What is here besides SQL

| File | Contents |
| --- | --- |
| `*.yml` | descriptions of every column, plus the tests that hold the grain and the arithmetic |
| [`customers.yml`](customers.yml) | the richest example: a model-level test that lifetime totals reconcile, and `accepted_values` on `customer_type` |
| [`orders.yml`](orders.yml) | two model-level reconciliation tests and a unit test for the boolean flags |
| [`order_items.yml`](order_items.yml) | a unit test for the aggregate-then-join pattern above |

Model-level tests (indented under `models:` rather than under a column) are the ones that check
relationships *between* columns — for example `order_total = subtotal + tax_paid`. That test is what
fails on purpose in Demo 2, and it is worth reading before the demo: breaking one line of
`stg_orders.sql` makes a test on a *different* model fail, and the three models downstream of it are
skipped rather than built on bad numbers.
