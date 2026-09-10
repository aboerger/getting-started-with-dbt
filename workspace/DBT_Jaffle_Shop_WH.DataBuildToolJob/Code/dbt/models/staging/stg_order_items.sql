{#
    stg_order_items - one row per item on an order. The finest grain in the project.

    A pure rename, like stg_customers: no logic, no filtering, one row out per row in. The only thing
    happening here is that the source's `sku` becomes `product_id`, so that every model downstream
    joins products on a column that is named the same everywhere.

    That consistency is the quiet payoff of a staging layer. `order_items.sql` joins four models
    together without a single cast or coalesce, because all four agree on what a key is called and
    what type it is.

    Its .yml file adds a `relationships` test - a foreign key from order_id to stg_orders, checked on
    every build, because Fabric will not enforce one.
#}

with

source as (

    select * from {{ source('ecom', 'raw_items') }}

),

renamed as (

    select

        ----------  ids
        id as order_item_id,
        order_id,
        sku as product_id

    from source

)

select * from renamed
