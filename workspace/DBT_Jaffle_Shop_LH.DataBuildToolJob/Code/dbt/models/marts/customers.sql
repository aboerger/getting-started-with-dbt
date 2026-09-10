{#
    customers - the model the whole talk builds toward. One row per customer, with lifetime totals.

    This is the first file so far that calls `{{ ref() }}` instead of `{{ source() }}`, and that is
    the distinction worth pausing on:

        {{ source('ecom', 'raw_customers') }}   someone else's table. dbt reads it, never builds it.
        {{ ref('stg_customers') }}              a model in this project. dbt builds it first.

    Each `ref` is an edge in the dependency graph. There are two here, so dbt knows to build
    stg_customers and orders before this model, and - because `orders` itself refs order_items, which
    refs four staging models - it works out the whole eleven-node chain behind this file without
    anyone writing a schedule. Add a ref and the graph changes; that is the entire orchestration
    story. Try `dbt ls --select +customers`.

    Materialized as a table (`+materialized: table` for the marts folder in dbt_project.yml), rebuilt
    from scratch on every run. No accumulated state means the table is always exactly what this code
    says it is.

    The shape of the query is the pattern every mart in this folder uses, and the one that prevents
    the most common warehouse bug:

        1. read each input into a named CTE          customers, orders
        2. aggregate to the grain you need          customer_orders_summary: one row per customer
        3. only then join, one row to one row        joined

    Joining `orders` directly to `customers` would fan one customer out into one row per order and
    silently multiply every total. Collapsing to the target grain first makes the join safe. The
    model-level test in customers.yml - lifetime_spend_pretax + lifetime_tax_paid = lifetime_spend -
    is what proves the arithmetic survived.

    Two portability details: the `group by` lists its columns explicitly because Spark SQL will not
    accept T-SQL's more forgiving forms, and `is_repeat_buyer` is produced by `to_bool` and read back
    by `is_true` because T-SQL has no boolean type. See ../../macros/booleans.sql.
#}

with

customers as (

    select * from {{ ref('stg_customers') }}

),

orders as (

    select * from {{ ref('orders') }}

),

customer_orders_summary as (

    select
        orders.customer_id,

        count(distinct orders.order_id) as count_lifetime_orders,
        {{ to_bool('count(distinct orders.order_id) > 1') }} as is_repeat_buyer,
        min(orders.ordered_at) as first_ordered_at,
        max(orders.ordered_at) as last_ordered_at,
        sum(orders.subtotal) as lifetime_spend_pretax,
        sum(orders.tax_paid) as lifetime_tax_paid,
        sum(orders.order_total) as lifetime_spend

    from orders

    group by orders.customer_id

),

joined as (

    select
        customers.*,

        customer_orders_summary.count_lifetime_orders,
        customer_orders_summary.first_ordered_at,
        customer_orders_summary.last_ordered_at,
        customer_orders_summary.lifetime_spend_pretax,
        customer_orders_summary.lifetime_tax_paid,
        customer_orders_summary.lifetime_spend,

        {# The business definition of a returning customer, written down once, in version control,
           and guarded by the accepted_values test in customers.yml. A left join means a customer with
           no orders at all falls through to 'new'. #}
        case
            when {{ is_true('customer_orders_summary.is_repeat_buyer') }} then 'returning'
            else 'new'
        end as customer_type

    from customers

    {# LEFT join, not inner: a customer who has never ordered must still appear in this mart. An
       inner join here would quietly drop them, and nobody would notice until a count disagreed. #}
    left join customer_orders_summary
        on customers.customer_id = customer_orders_summary.customer_id

)

select * from joined
