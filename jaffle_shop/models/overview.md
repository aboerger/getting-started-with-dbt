{#
    The landing page of the generated documentation site.

    `__overview__` is a reserved doc-block name: whatever is in it replaces dbt's default welcome
    page when you run

        dbt docs generate       builds target/index.html and target/catalog.json
        dbt docs serve          serves them on localhost

    Everything on that site is generated from files in this project - the descriptions in each .yml,
    the doc blocks in _shared__docs.md, and the lineage graph, which is read out of the ref() and
    source() calls in the SQL rather than maintained by hand. That is the point being made in Demo 3:
    the documentation is a build artefact, so it cannot drift away from the code.

    Keep the prose below free of Jinja braces. The content of a doc block is rendered as a template,
    so `ref()` written with braces would be evaluated rather than displayed.
#}

{% docs __overview__ %}

# Jaffle Shop on Microsoft Fabric

The companion project for the session **SQL as Software: Getting Started with dbt**.
It is the dbt Labs [Jaffle Shop](https://github.com/dbt-labs/jaffle-shop) sandwich-shop
dataset, ported to a portable SQL subset so that the same models build on:

| Target | Adapter | Dialect |
| --- | --- | --- |
| Fabric Warehouse `WH_Jaffle_Shop` | `dbt-fabric` | T-SQL |
| Fabric Lakehouse `LH_Jaffle_Shop` | `dbt-fabricspark` | Spark SQL |
| Fabric SQL database `DB_Jaffle_Shop` | `dbt-sqlserver` | T-SQL |

## Layers

- **Sources** (`raw` schema): six tables loaded by "ingestion" (here: `dbt seed`, once per target).
- **Staging** (`stg_*`, views): rename, cast cents to dollars, truncate timestamps. One row per source row.
- **Marts** (tables): `order_items` -> `orders` -> `customers`, plus the `products`, `locations` and `supplies` dimensions.

## Where to look first

- `customers`: one row per customer with lifetime order counts and spend, and `customer_type` (new / returning).
- `orders`: one row per order with cost, subtotal, item counts and food/drink flags.
- The tests on `stg_orders` and `orders` reconcile `order_total = subtotal + tax_paid`.

## How to read this site

Everything here was generated from the project by `dbt docs generate`. Nobody wrote a page.

- **Project view / Database view** (top left) switch between how the code is organised and how the
  objects are laid out in the warehouse.
- Each model's page shows its **description**, its **columns**, the **tests** attached to them, and
  the **compiled SQL** as it was sent to this engine. The description comes from the `.yml` file next
  to the model; longer explanations, such as the one on `customer_type`, come from a shared doc block
  in `_shared__docs.md`.
- The **lineage graph** (bottom right of any model page) is derived from the `ref()` and `source()`
  calls in the SQL. It is not maintained by anyone, and it cannot be out of date. Expand upstream
  from `customers` to see all the way back to the raw tables.
- The **Referenced by** list is the question that is normally impossible to answer: if this column
  changes, what breaks?

Two things are deliberately visible here. Sources appear as a distinct kind of node, marking the
boundary where this project's responsibility starts. And the tests are documentation too - a column
described as "the unique key" with `unique` and `not_null` beside it is a promise that gets checked
on every build.

{% enddocs %}
