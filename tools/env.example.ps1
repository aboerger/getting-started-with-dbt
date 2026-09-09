# Copy this file to tools/env.ps1 (git-ignored), fill in the values, then dot-source it:
#   . .\tools\env.ps1
# Everything profiles.yml needs comes from these variables. No secrets are required for
# interactive use: run `az login` once and the default authentication (CLI) is used.

# --- Fabric workspace and items --------------------------------------------------------------
$env:DBT_FABRIC_WORKSPACE_ID = "ad51bc60-66e8-45ac-9939-c54f343f54ce"

# Warehouse: "SQL connection string" from the Warehouse settings page.
$env:DBT_WAREHOUSE_HOST = "ujwmlees3dhelainntzwr6wnwm-mc6fdlpim2welgjzyvhtip2uzy.datawarehouse.fabric.microsoft.com"
$env:DBT_WAREHOUSE_NAME = "WH_Jaffle_Shop"

# Lakehouse: item id from the URL (.../lakehouses/<id>) or
#   fab get "/<workspace>.Workspace/LH_Jaffle_Shop.Lakehouse" -q id
$env:DBT_LAKEHOUSE_ID   = "<lakehouse item id>"
$env:DBT_LAKEHOUSE_NAME = "LH_Jaffle_Shop"

# SQL database: server and database name from the SQL database settings page ("Connection strings").
$env:DBT_SQLDB_HOST = "<xxxx>.database.fabric.microsoft.com"
$env:DBT_SQLDB_NAME = "DB_Jaffle_Shop-ae2739fc-db86-4e20-8b64-07b513427230"

# --- Target schema ---------------------------------------------------------------------------
# Use your own schema while developing (for example dev_andrew) and jaffle_shop for the demos.
$env:DBT_SCHEMA = "jaffle_shop"

# --- Authentication --------------------------------------------------------------------------
# CLI: `az login` (default).  environment: service principal via AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET.
$env:DBT_AUTH       = "CLI"    # dbt-fabric and dbt-sqlserver
$env:DBT_SPARK_AUTH = "CLI"    # dbt-fabricspark (CLI | SPN | fabric_notebook)
# $env:AZURE_TENANT_ID     = ""
# $env:AZURE_CLIENT_ID     = ""
# $env:AZURE_CLIENT_SECRET = ""
