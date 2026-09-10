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

{% enddocs %}
