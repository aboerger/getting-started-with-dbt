
        CREATE   VIEW "jaffle_shop"."stg_order_items" AS with

source as (

    select * from "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"."raw"."raw_items"

),

renamed as (

    select

        ----------  ids
        id as order_item_id,
        order_id,
        sku as product_id

    from source

)

select * from renamed;

GO

