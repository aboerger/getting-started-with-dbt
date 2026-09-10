{# Where every model gets built - and an example of overriding dbt's own behaviour.

   dbt calls a macro named `generate_schema_name` for every node in the project to decide which
   schema it belongs in. This file defines one, so this version is called instead of dbt's. Nothing
   registers it: dbt looks for the name, finds the root project's copy first, and uses it.

   The default implementation dbt ships concatenates the target schema and any custom schema
   (`jaffle_shop_marts`). This one is the upstream Jaffle Shop variant, kept because it does
   something this project needs: seeds go to a plain, shared `raw` schema while models go to the
   target's own schema.

   Why that matters here. `dbt_project.yml` sets `+schema: raw` on the seeds, and the two branches
   below turn that into:

     seeds                     -> raw                    shared, loaded once, treated as untouchable
     models (any target)       -> target.schema          jaffle_shop, or ci_1234 in the pipeline

   So the raw layer looks like data somebody else owns - which is the story the whole project tells -
   while every model still lands wherever the current target points. The CI target in profiles.yml
   builds into `ci_<build id>` and drops it afterwards, and nothing in this macro needs to know.

   This one macro is how a dbt project implements its environment strategy: schema per developer,
   schema per pull request, one schema in production. It is worth knowing it exists before you need
   it, because the alternative - hard-coding schema names in models - is very hard to undo.

   `node` carries everything dbt knows about the thing being built (resource_type, name, path, tags,
   config), and `target` describes the connection in use, so any policy you can express in Jinja is
   available here.
#}

{% macro generate_schema_name(custom_schema_name, node) %}

    {% set default_schema = target.schema %}

    {# seeds go in a global `raw` schema #}
    {% if node.resource_type == 'seed' %}
        {{ custom_schema_name | trim }}

    {# non-specified schemas go to the default target schema #}
    {% elif custom_schema_name is none %}
        {{ default_schema }}


    {# specified custom schema names go to the schema name prepended with the the default schema name in prod (as this is an example project we want the schemas clearly labeled) #}
    {% elif target.name == 'prod' %}
        {{ default_schema }}_{{ custom_schema_name | trim }}

    {# specified custom schemas go to the default target schema for non-prod targets #}
    {% else %}
        {{ default_schema }}
    {% endif %}

{% endmacro %}
