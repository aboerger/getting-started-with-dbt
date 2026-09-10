{#
    locations - the store dimension. Six rows, published as a table.

    A pass-through of stg_locations; products.sql explains why a mart that transforms nothing is
    still worth having.

    Worth noticing here: the source table is `raw_stores`, the source column is `store_id`, and this
    model is called locations with a location_id. The rename happened once, in the staging layer, and
    from there on the project speaks the business's language. Nobody querying this mart needs to know
    that the source system calls them stores.
#}

with

locations as (

    select * from {{ ref('stg_locations') }}

)

select * from locations
