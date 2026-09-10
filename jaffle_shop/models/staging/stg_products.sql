{#
    stg_products - where the food/drink flags are born.

    The source has a `type` column containing 'jaffle' or 'beverage'. Two boolean columns are derived
    from it here, once, so that no downstream model and no report ever repeats the string comparison.
    That is the difference between a data warehouse and a folder of queries: the definition of "is
    this food?" is written down in one place, in version control, and tested.

    `{{ to_bool("type = 'jaffle'") }}` is a macro call and not plain SQL for a blunt reason: T-SQL has
    no boolean type, and will not accept a boolean expression in a select list at all. The macro
    renders `cast(case when type = 'jaffle' then 1 else 0 end as bit)` on the two T-SQL targets and
    `coalesce(type = 'jaffle', false)` on the Spark target. Same file, three engines - Demo 4.

    Because the result is a `bit` on T-SQL, reading the column back also needs care: see the
    `is_true` macro, used in orders.sql. Both live in ../../macros/booleans.sql.
#}

with

source as (

    select * from {{ source('ecom', 'raw_products') }}

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
        {{ cents_to_dollars('price') }} as product_price,

        ---------- booleans
        {{ to_bool("type = 'jaffle'") }} as is_food_item,

        {{ to_bool("type = 'beverage'") }} as is_drink_item

    from source

)

select * from renamed
