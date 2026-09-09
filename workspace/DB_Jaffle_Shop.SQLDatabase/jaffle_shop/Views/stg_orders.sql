
        CREATE   VIEW "jaffle_shop"."stg_orders" AS with

source as (

    select * from "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"."raw"."raw_orders"

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
        cast(subtotal / 100.0 as numeric(16, 2)) as subtotal,
        cast(tax_paid / 100.0 as numeric(16, 2)) as tax_paid,
        cast(order_total / 100.0 as numeric(16, 2)) as order_total,

        ---------- timestamps
        cast(ordered_at as date) as ordered_at

    from source

)

select * from renamed;

GO

