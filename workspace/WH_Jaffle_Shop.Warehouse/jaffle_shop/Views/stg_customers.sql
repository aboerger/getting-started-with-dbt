-- Auto Generated (Do not modify) 8550F8CEFA3677C413D08D33D7BD85E824C33C87C92391A9E155907269130706
create view [jaffle_shop].[stg_customers] as with

source as (

    select * from [WH_Jaffle_Shop].[raw].[raw_customers]

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