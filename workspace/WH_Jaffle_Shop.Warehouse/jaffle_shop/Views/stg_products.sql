-- Auto Generated (Do not modify) C79FE743BAB482B9606E7CEBB8C59C2A284E82EACD75953B2C7DAD7FD99E9724
create view [jaffle_shop].[stg_products] as with

source as (

    select * from [WH_Jaffle_Shop].[raw].[raw_products]

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