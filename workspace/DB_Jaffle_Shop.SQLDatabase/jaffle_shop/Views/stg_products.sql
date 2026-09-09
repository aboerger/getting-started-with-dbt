
        CREATE   VIEW "jaffle_shop"."stg_products" AS with

source as (

    select * from "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"."raw"."raw_products"

),

renamed as (

    select

        ----------  ids
        sku as product_id,

        ---------- text
        name as product_name,
        type as product_type,
        description as product_description,


        ---------- numerics
        cast(price / 100.0 as numeric(16, 2)) as product_price,

        ---------- booleans
        cast(case when type = 'jaffle' then 1 else 0 end as bit) as is_food_item,

        cast(case when type = 'beverage' then 1 else 0 end as bit) as is_drink_item

    from source

)

select * from renamed;

GO

