{# Project-level dispatch overrides for the two T-SQL adapters. dbt searches the root project first
   for adapter-prefixed macros in every namespace (dbt, dbt_utils), so these win on fabric / sqlserver
   and the Spark target keeps the defaults. Each one exists because of a concrete difference found
   while building this project on Fabric. They are deliberately self-contained: a dispatched macro
   runs in the calling package's context, where other root-project macros are not in scope.

   1. dbt_utils.expression_is_true renders `select 1 from ... where not(expr)`. dbt-fabric and
      dbt-sqlserver wrap every test in `with test_main_sql as (...)`, and a CTE column needs a name
      in T-SQL ("No column name was specified for column 1 of 'test_main_sql'").

   2. The adapters implement date_trunc as CAST(DATEADD(day, DATEDIFF(day, 0, x), 0) AS DATE). The
      literal 0 is a legacy datetime, so a datetime2 value such as 23:59:59.9999 rounds up to the
      next day before it is truncated. The upstream unit test on stg_locations catches exactly this.
#}

{# ---- 1. dbt_utils.expression_is_true --------------------------------------------------------- #}

{% macro fabric__test_expression_is_true(model, expression, column_name=none) %}

{% set column_list = '*' if should_store_failures() else "1 as failing_row" %}

select
    {{ column_list }}
from {{ model }}
{% if column_name is none %}
where not({{ expression }})
{%- else %}
where not({{ column_name }} {{ expression }})
{%- endif %}

{% endmacro %}


{% macro sqlserver__test_expression_is_true(model, expression, column_name=none) %}

{% set column_list = '*' if should_store_failures() else "1 as failing_row" %}

select
    {{ column_list }}
from {{ model }}
{% if column_name is none %}
where not({{ expression }})
{%- else %}
where not({{ column_name }} {{ expression }})
{%- endif %}

{% endmacro %}


{# ---- 2. dbt.date_trunc ------------------------------------------------------------------------ #}

{% macro fabric__date_trunc(datepart, date) -%}
    {%- if datepart | lower == 'day' -%}
    cast({{ date }} as date)
    {%- else -%}
    datetrunc({{ datepart }}, {{ date }})
    {%- endif -%}
{%- endmacro %}

{% macro sqlserver__date_trunc(datepart, date) -%}
    {%- if datepart | lower == 'day' -%}
    cast({{ date }} as date)
    {%- else -%}
    datetrunc({{ datepart }}, {{ date }})
    {%- endif -%}
{%- endmacro %}
