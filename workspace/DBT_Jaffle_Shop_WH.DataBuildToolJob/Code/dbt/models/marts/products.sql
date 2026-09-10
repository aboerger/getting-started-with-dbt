{#
    products - the product dimension, and a fair question: why does this file exist?

    It is `select *` from a staging view. It transforms nothing. Deleting it and pointing everyone at
    stg_products would produce identical numbers today.

    It exists because a mart is a published interface. Reports, analysts and other projects point at
    `products`; the staging layer stays private to the data team. That boundary costs one file and
    buys the freedom to change how the dimension is built - add a supplier join, add slowly-changing
    history, swap the source system - without any consumer changing anything.

    It is also free at query time. The marts folder is materialized as tables, so a consumer reads a
    real table rather than a chain of views resolving down to the raw schema on every query.

    The same reasoning applies to locations.sql and supplies.sql. When you see a one-line model in a
    dbt project, this is usually why.
#}

with

products as (

    select * from {{ ref('stg_products') }}

)

select * from products
