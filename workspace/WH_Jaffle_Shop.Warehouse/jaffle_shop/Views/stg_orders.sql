-- Auto Generated (Do not modify) 6863A55FC1FE55E79A6E12918E911FD9C3379B62AD60345EC54EB8EBBAD98AB9
create view [jaffle_shop].[stg_orders] as with

source as (

    select * from [WH_Jaffle_Shop].[raw].[raw_orders]

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