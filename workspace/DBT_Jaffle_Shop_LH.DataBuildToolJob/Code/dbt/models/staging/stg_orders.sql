{#
    stg_orders - the staging model that does the most work, and the one Demo 2 breaks.

    Three jobs beyond renaming, and each is an example of something staging models are for:

      1. Vocabulary. The source calls them `customer` and `store_id`; the business says customer and
         location. Renaming here means the eleven models downstream never see the source system's
         words, and an upstream rename changes exactly this file.

      2. Units. Money arrives as integer cents - correct for a transactional system, useless in a
         report. `cents_to_dollars` converts it, and both forms are kept: subtotal_cents for
         reconciling against the source, subtotal for everyone else.

      3. Precision. `ordered_at` is a timestamp; every question anyone asks of it is by day. Truncate
         once here rather than in every downstream query.

    Portability: `cents_to_dollars` and `dbt.date_trunc` are macro calls rather than SQL because the
    type name and the truncation syntax differ between T-SQL and Spark SQL. This file compiles for
    all three targets. See ../../macros/README.md.

    Demo 2 breaks this model by leaving tax_paid in cents, which makes the reconciliation test in
    stg_orders.yml (`order_total - tax_paid = subtotal`) fail on 61,465 of 61,948 rows - and dbt then
    skips order_items, orders and customers rather than building them on numbers that do not add up.
    `tools\scenario.ps1 break` does it by replacing one line below, so leave that line alone; `reset`
    restores it with `git checkout`, because it is code and Git is the undo button.
#}

with

source as (

    select * from {{ source('ecom', 'raw_orders') }}

),

renamed as (

    select

        ----------  ids
        id as order_id,
        store_id as location_id,
        customer as customer_id,

        ---------- numerics
        subtotal as subtotal_cents,
        tax_paid as tax_paid_cents,
        order_total as order_total_cents,
        {{ cents_to_dollars('subtotal') }} as subtotal,
        {{ cents_to_dollars('tax_paid') }} as tax_paid,
        {{ cents_to_dollars('order_total') }} as order_total,

        ---------- timestamps
        {{ dbt.date_trunc('day','ordered_at') }} as ordered_at

    from source

)

select * from renamed
