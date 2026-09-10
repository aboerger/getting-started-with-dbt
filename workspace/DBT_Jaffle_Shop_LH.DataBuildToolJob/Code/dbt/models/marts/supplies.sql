{#
    supplies - the supply dimension, published as a table.

    A pass-through of stg_supplies; products.sql explains why these one-line marts exist.

    Mind the grain if you query this table: one row per supply *per product*, keyed by the surrogate
    key stg_supplies builds by hashing id and sku together. Summing supply_cost across a join to this
    table without aggregating first is the fan-out bug that order_items.sql goes out of its way to
    avoid - and that its unit test guards.
#}

with

supplies as (

    select * from {{ ref('stg_supplies') }}

)

select * from supplies
