{# T-SQL has no boolean type and no boolean-valued expressions in a SELECT list; Spark SQL has both.
   Two tiny macros keep the models identical across Fabric Warehouse, Fabric SQL database and
   Fabric Lakehouse:

     to_bool("type = 'jaffle'")  -> boolean column     (Spark: coalesce(expr, false); T-SQL: bit)
     is_true('is_food_item')     -> boolean predicate  (Spark: col;                    T-SQL: col = 1)
#}

{% macro to_bool(expression) -%}
    {{ return(adapter.dispatch('to_bool')(expression)) }}
{%- endmacro %}

{% macro default__to_bool(expression) -%}
    coalesce({{ expression }}, false)
{%- endmacro %}

{% macro fabric__to_bool(expression) -%}
    cast(case when {{ expression }} then 1 else 0 end as bit)
{%- endmacro %}

{% macro sqlserver__to_bool(expression) -%}
    cast(case when {{ expression }} then 1 else 0 end as bit)
{%- endmacro %}


{% macro is_true(column_name) -%}
    {{ return(adapter.dispatch('is_true')(column_name)) }}
{%- endmacro %}

{% macro default__is_true(column_name) -%}
    {{ column_name }}
{%- endmacro %}

{% macro fabric__is_true(column_name) -%}
    {{ column_name }} = 1
{%- endmacro %}

{% macro sqlserver__is_true(column_name) -%}
    {{ column_name }} = 1
{%- endmacro %}
