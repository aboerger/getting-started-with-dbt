{# Used by CI to remove the per-run schema after the build:
     dbt run-operation drop_schema_if_exists --args "{schema_name: ci_1234}" --target ci #}

{% macro drop_schema_if_exists(schema_name) %}
    {% set relation = api.Relation.create(database=target.database, schema=schema_name) %}
    {% do adapter.drop_schema(relation) %}
    {{ log("Dropped schema " ~ target.database ~ "." ~ schema_name ~ " (if it existed)", info=True) }}
{% endmacro %}
