{#
    order_items - one row per item on an order, enriched with product and supply detail.

    The bottom of the mart chain: orders is built by aggregating this, and customers by aggregating
    orders. Four staging models come together here.

    This model is the clearest example of the aggregate-then-join rule, because it has to break it
    for one input and not for the others:

      * products and orders are one row per product and per order, so they can be joined directly.
      * supplies is NOT. stg_supplies holds one row per supply per product - a product with three
        supplies has three rows. Joining it straight to order_items would turn one item into three
        and triple every cost that anything downstream computes.

    So `order_supplies_summary` collapses supplies to one row per product *first*, and only then is
    it joined. That is the entire reason the CTE exists, and the unit test
    `test_supply_costs_sum_correctly` in order_items.yml exists to make sure nobody ever "simplifies"
    it away: it feeds two supply rows for one product and asserts the cost arrives summed, not
    duplicated.

    Every join is a LEFT join. An order item must survive into this table even if its product or its
    supplies are missing, so that the row shows up as a null cost to investigate rather than
    disappearing from the mart entirely. Silent row loss is much harder to notice than a null.
#}

with

order_items as (

    select * from {{ ref('stg_order_items') }}

),


orders as (

    select * from {{ ref('stg_orders') }}

),

products as (

    select * from {{ ref('stg_products') }}

),

supplies as (

    select * from {{ ref('stg_supplies') }}

),

{# Collapse supplies from one-row-per-supply-per-product down to one row per product, so that the
   join below cannot fan out. Aggregate first, join second - always in this order. #}
order_supplies_summary as (

    select
        product_id,

        sum(supply_cost) as supply_cost

    from supplies

    group by product_id

),

joined as (

    select
        order_items.*,

        orders.ordered_at,

        products.product_name,
        products.product_price,
        products.is_food_item,
        products.is_drink_item,

        order_supplies_summary.supply_cost

    from order_items

    left join orders on order_items.order_id = orders.order_id

    left join products on order_items.product_id = products.product_id

    {# Safe to join one-to-one now, because of the aggregation above. #}
    left join order_supplies_summary
        on order_items.product_id = order_supplies_summary.product_id

)

select * from joined
