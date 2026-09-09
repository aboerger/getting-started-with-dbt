
        CREATE   VIEW "jaffle_shop"."stg_customers" AS with

source as (

    select * from "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"."raw"."raw_customers"

),

renamed as (

    select

        ----------  ids
        id as customer_id,

        ---------- text
        name as customer_name

    from source

)

select * from renamed;

GO

