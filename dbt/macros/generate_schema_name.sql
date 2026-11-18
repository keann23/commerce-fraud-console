-- Use the configured schema name as-is ("dbt"), not dbt's default "<target>_<custom>" concatenation.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
