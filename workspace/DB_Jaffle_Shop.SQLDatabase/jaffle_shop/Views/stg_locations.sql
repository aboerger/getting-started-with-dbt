
        CREATE   VIEW "jaffle_shop"."stg_locations" AS with

source as (

    select * from "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"."raw"."raw_stores"

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

GO

