-- Auto Generated (Do not modify) C90FA81F0B681EB93C32EBE0B52BDAE714D4D7C67F15268BD33EEDC8EA8885AA
create view [jaffle_shop].[stg_order_items] as with

source as (

    select * from [WH_Jaffle_Shop].[raw].[raw_items]

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