{# Cast an integer cents column to a dollar amount. One macro, one dialect difference:
   the default (Spark SQL) and the T-SQL variants differ only in the numeric type name.
   Dividing by 100.0 (not 100) keeps T-SQL from doing integer division. #}

{% macro cents_to_dollars(column_name) -%}
    {{ return(adapter.dispatch('cents_to_dollars')(column_name)) }}
{%- endmacro %}

{% macro default__cents_to_dollars(column_name) -%}
    cast({{ column_name }} / 100.0 as decimal(16, 2))
{%- endmacro %}

{% macro fabric__cents_to_dollars(column_name) -%}
    cast({{ column_name }} / 100.0 as numeric(16, 2))
{%- endmacro %}

{% macro sqlserver__cents_to_dollars(column_name) -%}
    cast({{ column_name }} / 100.0 as numeric(16, 2))
{%- endmacro %}
