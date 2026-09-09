
        CREATE   VIEW "jaffle_shop"."stg_supplies" AS with

source as (

    select * from "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"."raw"."raw_supplies"

),

renamed as (

    select

        ----------  ids
        
    lower(convert(varchar(50), hashbytes('md5', coalesce(convert(varchar(8000), concat(coalesce(cast(id as VARCHAR(8000)), '_dbt_utils_surrogate_key_null_'), '-', coalesce(cast(sku as VARCHAR(8000)), '_dbt_utils_surrogate_key_null_'))), '')), 2))
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

GO

