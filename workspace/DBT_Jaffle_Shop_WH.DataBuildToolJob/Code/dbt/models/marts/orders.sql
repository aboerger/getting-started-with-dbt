{#
    orders - one row per order, in the middle of the chain: order_items -> orders -> customers.

    Note that this model refs a staging model *and* another mart. Marts are allowed to build on
    marts, and the alternative - re-deriving item counts from stg_order_items here and again in
    customers - is how a project ends up with three definitions of the same number.

    Three techniques worth reading for:

      1. Aggregate, then join. `order_items_summary` reduces items to one row per order before it is
         joined, for the same reason as everywhere else in this folder. The test
         `order_items_subtotal = subtotal` in orders.yml is the proof: this project's sum of item
         prices must equal the subtotal the source system sent.

      2. Counting with a `case` expression instead of a filter. `sum(case when is_food_item then 1
         else 0 end)` counts food items and drink items in the same pass over the data - two numbers,
         one scan, no self-join. `is_true()` wraps the column because on T-SQL it is a `bit` and
         `case when is_food_item` is not valid there; on Spark it renders as the bare column.

      3. A window function. `row_number() over (partition by customer_id order by ordered_at)` numbers
         each customer's orders, so customer_order_number = 1 marks a first order. Window functions
         are the one place SQL beats every other transformation tool, and they need no special
         handling in dbt at all - it is just SQL.

    The booleans come from `to_bool` for the usual reason: counts are turned into is_food_order and
    is_drink_order flags here, and T-SQL cannot put a boolean expression in a select list. The unit
    test in orders.yml pins that conversion down, including the null case - an order with no drinks
    must come out false, not null.
#}

with

orders as (

    select * from {{ ref('stg_orders') }}

),

order_items as (

    select * from {{ ref('order_items') }}

),

{# One row per order, so the join below is one-to-one. See the header. #}
order_items_summary as (

    select
        order_id,

        sum(supply_cost) as order_cost,
        sum(product_price) as order_items_subtotal,
        count(order_item_id) as count_order_items,
        sum(
            case
                when {{ is_true('is_food_item') }} then 1
                else 0
            end
        ) as count_food_items,
        sum(
            case
                when {{ is_true('is_drink_item') }} then 1
                else 0
            end
        ) as count_drink_items

    from order_items

    {# Explicit column, not `group by 1`: Spark SQL and T-SQL disagree about the shorthands, and
       being explicit is what keeps this file compiling on both. #}
    group by order_id

),

compute_booleans as (

    select
        orders.*,

        order_items_summary.order_cost,
        order_items_summary.order_items_subtotal,
        order_items_summary.count_food_items,
        order_items_summary.count_drink_items,
        order_items_summary.count_order_items,
        {{ to_bool('order_items_summary.count_food_items > 0') }} as is_food_order,
        {{ to_bool('order_items_summary.count_drink_items > 0') }} as is_drink_order

    from orders

    left join
        order_items_summary
        on orders.order_id = order_items_summary.order_id

),

{# Number each customer's orders by date, so 1 is their first. A window function does this in one
   pass; the alternative is a self-join to a min(ordered_at) per customer. #}
customer_order_count as (

    select
        *,

        row_number() over (
            partition by customer_id
            order by ordered_at asc
        ) as customer_order_number

    from compute_booleans

)

select * from customer_order_count
