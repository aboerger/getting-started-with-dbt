<#
.SYNOPSIS
  Creates one pinned Python environment per dbt adapter, exactly as rehearsed.

.DESCRIPTION
  .venv-warehouse  dbt-core 1.11 + dbt-fabric       (Fabric Warehouse, T-SQL, mssql-python driver)
  .venv-lakehouse  dbt-core 1.11 + dbt-fabricspark  (Fabric Lakehouse, Spark SQL over Livy)
  .venv-sqldb      dbt-core 1.11 + dbt-sqlserver    (Fabric SQL database, T-SQL, ODBC Driver 18)
  .venv-tools      the lakehouse stack + pip, azure-storage-file-datalake, pytest: publishes the
                   OneLake bundle NB_dbt_Runner_Spark runs (tools/publish_dbt_bundle.py) and runs the tool tests

  Requires uv (https://docs.astral.sh/uv/) and Python 3.11. Re-run at any time; it is idempotent.
  Pass -Target to build a single environment.

.EXAMPLE
  .\tools\setup-env.ps1
  .\tools\setup-env.ps1 -Target lakehouse
#>
[CmdletBinding()]
param(
    [ValidateSet('warehouse', 'lakehouse', 'sqldb', 'tools', 'all')]
    [string]$Target = 'all'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed. Install it with: winget install astral-sh.uv"
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Warning "Azure CLI (az) is not installed. The default profile authentication (CLI) needs it: winget install Microsoft.AzureCLI"
}

$targets = if ($Target -eq 'all') { @('warehouse', 'lakehouse', 'sqldb', 'tools') } else { @($Target) }

foreach ($t in $targets) {
    $venv = ".venv-$t"
    Write-Host "== $venv" -ForegroundColor Cyan
    uv venv $venv --python 3.11 --allow-existing
    uv pip sync "requirements/$t.txt" --python "$venv/Scripts/python.exe"
    & "$venv/Scripts/dbt.exe" --version
}

Write-Host ""
Write-Host "Done. Activate one environment, load your variables, and run dbt from the project folder:" -ForegroundColor Green
Write-Host "  .\.venv-warehouse\Scripts\Activate.ps1"
Write-Host "  . .\tools\env.ps1          # copy tools\env.example.ps1 first"
Write-Host "  cd jaffle_shop; dbt deps; dbt debug --target warehouse"
