{#
    stg_locations - six rows, and one line that hides a bug.

    The rename is the interesting part of the model itself: the source table is `raw_stores` with a
    `name` column, and it comes out as stg_locations with location_id and location_name. The business
    says "location", so the staging layer translates once and nothing downstream has to remember.

    The line to look at is `{{ dbt.date_trunc('day', 'opened_at') }}`. Note the `dbt.` prefix: this
    is not a macro from this project but one of dbt's own cross-database functions, which every
    adapter implements in its own dialect. Calling it instead of writing `cast(... as date)` or
    `date_trunc(day, ...)` is what lets this file compile for T-SQL and Spark SQL alike.

    It is also where a genuine bug lived. Fabric's adapters implement date_trunc as
    `CAST(DATEADD(day, DATEDIFF(day, 0, x), 0) AS DATE)`, and that literal 0 is a legacy `datetime`,
    so a `datetime2` of 23:59:59.9999 rounds *up* to the next midnight before being truncated - a row
    landing on the wrong day. The project overrides date_trunc for the two T-SQL adapters in
    ../../macros/tsql_overrides.sql, and the unit test in stg_locations.yml is what found it and
    what keeps it fixed.

    A useful thing to say out loud about that: the bug was in the tooling, not in this project's SQL,
    and it was still catchable - because a unit test asks "what does this model produce for this
    input?" without needing an opinion about where the mistake is.
#}

with

source as (

    select * from {{ source('ecom', 'raw_stores') }}

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
        {{ dbt.date_trunc('day', 'opened_at') }} as opened_date

    from source

)

select * from renamed
