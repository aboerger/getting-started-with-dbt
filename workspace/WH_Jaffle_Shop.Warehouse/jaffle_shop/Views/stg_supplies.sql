-- Auto Generated (Do not modify) DBFDF9534FD61E80CE74401D82413C9C51C645A88C6E70315EEC09E9B7A1D9D1
create view [jaffle_shop].[stg_supplies] as with

source as (

    select * from [WH_Jaffle_Shop].[raw].[raw_supplies]

),

renamed as (

    select

        ----------  ids
        
    lower(convert(varchar(50), hashbytes('md5', coalesce(convert(varchar(max), concat(coalesce(cast(id as VARCHAR(MAX)), '_dbt_utils_surrogate_key_null_'), '-', coalesce(cast(sku as VARCHAR(MAX)), '_dbt_utils_surrogate_key_null_'))), '')), 2))
 as supply_uuid,
        id as supply_id,
        sku as product_id,

        ---------- text
        name as supply_name,

        ---------- numerics
        cast(cost / 100.0 as numeric(16, 2)) as supply_cost,

        ---------- booleans
        perishable as is_perishable_supply

    from source

)

select * from renamed;