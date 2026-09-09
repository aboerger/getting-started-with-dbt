-- Auto Generated (Do not modify) 8B0BFBB08D94AF1CDA29C4A8727304BA1835E5E83D6FDF13AF36EE2EFF4CC2B1
create view [jaffle_shop].[stg_locations] as with

source as (

    select * from [WH_Jaffle_Shop].[raw].[raw_stores]

),

renamed as (

    select

        ----------  ids
        id as location_id,

        ---------- text
        name as location_name,

        ---------- numerics
        tax_rate,

        ---------- timestamps
        cast(opened_at as date) as opened_date

    from source

)

select * from renamed;