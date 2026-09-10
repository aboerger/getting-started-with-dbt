{#
    stg_customers - the simplest model in the project. Start here.

    Everything a dbt model is, in fourteen lines of SQL:

      * One `select` statement. No CREATE, no DROP, no INSERT, no transaction handling. dbt wraps
        this in `create view jaffle_shop.stg_customers as (...)` because dbt_project.yml sets
        `+materialized: view` for this folder. Change that one word to `table` and dbt emits a
        CREATE TABLE AS instead - without this file changing at all.

      * `{{ source('ecom', 'raw_customers') }}` instead of a table name. It compiles to
        `raw.raw_customers`, declared in __sources.yml. Because dbt reads this call out of the SQL,
        it knows this model depends on that table - the lineage graph is derived, never declared.

      * No schema name anywhere. The target decides: your development schema, a CI schema, or
        production, from profiles.yml. The same file deploys to all of them.

    The two-CTE shape (`source` then `renamed`) and the `---------- ids` banners are convention, not
    requirement. Every staging model in the folder looks like this so that they are all reviewable at
    a glance. See README.md in this folder.

    This header is a *Jinja* comment - the brace-and-hash delimiters, rather than SQL's `--`. dbt
    strips it at compile time, so it never reaches the database and the view definition in the
    warehouse stays clean. The `----------` banners below are ordinary SQL comments and do survive
    into the compiled SQL: compare the two in
    target/compiled/jaffle_shop/models/staging/stg_customers.sql after a build.
#}

with

source as (

    select * from {{ source('ecom', 'raw_customers') }}

),

renamed as (

    select

        ----------  ids
        id as customer_id,

        ---------- text
        name as customer_name

    from source

)

select * from renamed
