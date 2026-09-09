<#
.SYNOPSIS
  Demo 2 helper: break the project on purpose, then put it back.

.DESCRIPTION
  break : edits models/staging/stg_orders.sql so tax_paid is no longer converted from cents to
          dollars. The reconciliation test `order_total - tax_paid = subtotal` on stg_orders fails,
          and dbt build skips everything downstream (order_items, orders, customers).
  reset : restores the model from Git (git checkout). It is code, so Git is the undo button.
  status: shows whether the model is currently broken.

.EXAMPLE
  .\tools\scenario.ps1 break
  dbt build --select stg_orders+      # from jaffle_shop/: FAIL on stg_orders, downstream SKIPPED
  .\tools\scenario.ps1 reset
  dbt build --select stg_orders+      # green again
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('break', 'reset', 'status')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$repo  = Split-Path -Parent $PSScriptRoot
$model = Join-Path $repo 'jaffle_shop\models\staging\stg_orders.sql'
$good  = "{{ cents_to_dollars('tax_paid') }} as tax_paid,"
$bad   = "tax_paid as tax_paid,  -- BUG: still in cents"

$content = Get-Content $model -Raw
switch ($Action) {
    'break' {
        if ($content.Contains($bad)) { Write-Host "Already broken."; break }
        if (-not $content.Contains($good)) { throw "Expected line not found in $model" }
        Set-Content $model ($content.Replace($good, $bad)) -NoNewline
        Write-Host "Broke stg_orders.sql: tax_paid is left in cents." -ForegroundColor Yellow
        Write-Host "Now run:  dbt build --select stg_orders+"
    }
    'reset' {
        git -C $repo checkout -- 'jaffle_shop/models/staging/stg_orders.sql'
        Write-Host "Restored stg_orders.sql from Git." -ForegroundColor Green
    }
    'status' {
        if ($content.Contains($bad)) { Write-Host "stg_orders.sql is BROKEN (tax_paid in cents)." -ForegroundColor Yellow }
        else { Write-Host "stg_orders.sql is intact." -ForegroundColor Green }
    }
}
