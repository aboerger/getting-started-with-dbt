{#
    stg_supplies - the model with a surrogate key.

    The grain here is the trap. `raw_supplies` holds one row per supply *per product*, and costs
    change over time, so neither `id` nor `sku` is unique on its own. There is no single column that
    identifies a row.

    `dbt_utils.generate_surrogate_key(['id', 'sku'])` builds one by hashing the two together. It comes
    from the dbt_utils package (see ../../packages.yml) and, like the project's own macros, renders
    the right dialect per engine - an MD5 of the concatenated, null-safe, cast columns.

    Why bother: a single key column is what makes `unique` and `not_null` in stg_supplies.yml able to
    guard the grain. Without it there is nothing to test, and nothing to join on predictably.

    This is also the model that the aggregate-before-you-join lesson in ../marts/order_items.sql is
    about. Read stg_supplies.yml's description before joining anything to this model.
#}

with

source as (

    select * from {{ source('ecom', 'raw_supplies') }}

),

renamed as (

    select

        ----------  ids
        {{ dbt_utils.generate_surrogate_key(['id', 'sku']) }} as supply_uuid,
        id as supply_id,
        sku as product_id,

        ---------- text
        name as supply_name,

        ---------- numerics
        {{ cents_to_dollars('cost') }} as supply_cost,

        ---------- booleans
        perishable as is_perishable_supply

    from source

)

select * from renamed
