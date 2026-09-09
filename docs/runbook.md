# Demo runbook

Five demos, one project, three engines. Times match the speaker notes in the deck.
Expected numbers were computed from the seed data and must match every engine.

| Metric | Expected |
| --- | --- |
| customers | 935 (new 6, returning 929) |
| orders | 61,948 (Sep 2024 - Aug 2025, two stores) |
| order_items | 90,900 |
| sum(lifetime_spend) | 671,425.37 (new 113.48, returning 671,311.89) |
| dbt build node count | 48 = 12 models + 33 data tests + 3 unit tests |
| Demo 2 selection (`stg_orders+`) | 22 nodes: PASS=4 ERROR=1 SKIP=17 |

## Before the talk (the evening before)

1. Pull `main`; `tools\setup-env.ps1`; `. .\tools\env.ps1`; `az login`.
2. Raw tables loaded on all three engines (only once; this is the slow part):

   ```powershell
   cd jaffle_shop
   .\..\.venv-warehouse\Scripts\Activate.ps1; dbt seed --vars '{"load_source_data": true}' --target warehouse
   .\..\.venv-lakehouse\Scripts\Activate.ps1; dbt seed --vars '{"load_source_data": true}' --target lakehouse
   .\..\.venv-sqldb\Scripts\Activate.ps1;     dbt seed --vars '{"load_source_data": true}' --target sqldb
   ```

   Seeds go through batched INSERT statements (400 rows per statement on T-SQL), so expect tens of minutes on the
   Warehouse and the Lakehouse; record the actual duration here once measured.
3. `dbt build` green on all three targets (`--target warehouse`, `lakehouse`, `sqldb`).
4. `dbt docs generate` then `dbt docs serve --port 8080` in a spare terminal; leave the browser tab open on `customers`.
5. `tools\scenario.ps1 status` says intact; `git status` clean.
6. Warm the Spark session: `dbt run --select stg_products --target lakehouse` ten minutes before Demo 4.
7. Fallback recordings of Demo 4 (Spark) and Demo 5 ready to play.
8. Terminal font large; `.venv-warehouse` active; working directory `jaffle_shop`.

## Demo 1 · Fabric Warehouse · Build a useful mart (10:00-19:00)

```powershell
code models\staging\__sources.yml models\staging\stg_orders.sql models\marts\customers.yml
dbt build
code target\compiled\jaffle_shop\models\marts\customers.sql
```

Expected console tail: `Done. PASS=48 WARN=0 ERROR=0 SKIP=0 TOTAL=48` (seeds are not part of the build).

Query in the Warehouse (or `dbt show --inline`):

```sql
select customer_type, count(*) as customers, sum(lifetime_spend) as lifetime_spend
from jaffle_shop.customers
group by customer_type;
```

| customer_type | customers | lifetime_spend |
| --- | ---: | ---: |
| new | 6 | 113.48 |
| returning | 929 | 671,311.89 |

Talking points: source() vs ref() in the compiled SQL; the `raw` schema is "someone else's" data; only six customers are
new after a year because the data is regulars.

Recovery: if the build fails on connectivity, `dbt debug`; if `az login` has expired, log in again in a second terminal
while talking. If time is short, `dbt build --selector demo1` builds the customer branch only (35 nodes).

## Demo 2 · Fabric Warehouse · Break it on purpose (24:00-33:00)

```powershell
..\tools\scenario.ps1 break          # one line in stg_orders.sql: tax_paid stays in cents
git diff                             # show it
dbt build --select stg_orders+
$LASTEXITCODE                        # 1
```

Expected: `PASS view stg_orders`, `FAIL 61948 dbt_utils_expression_is_true_stg_orders_order_total_tax_paid_subtotal`,
`SKIP` for `order_items`, `orders`, `customers`, their tests and the two unit tests. Summary
`Done. PASS=4 WARN=0 ERROR=1 SKIP=17 TOTAL=22`.

Show: `target\compiled\jaffle_shop\models\staging\stg_orders.yml\dbt_utils_expression_is_true_...sql` and
`target\run_results.json`. Prove the old `customers` table still answers the Demo 1 query.

```powershell
..\tools\scenario.ps1 reset          # git checkout of the model
dbt build --select stg_orders+       # PASS=22
```

Variant if time remains: change `'returning'` to `'Returning'` in `customers.sql`; `dbt build --select customers` fails
`accepted_values_customers_customer_type__new__returning`.

Recovery: `..\tools\scenario.ps1 reset` always restores the file; `git checkout -- .` restores anything else.

## Demo 3 · dbt docs · Follow the lineage (35:00-39:00)

Browser tab already open at `http://localhost:8080`. Search `customers`, read description and columns, open the
lineage graph (bottom right), expand upstream.

```powershell
dbt ls --select +customers --resource-type model --resource-type source
dbt ls --select stg_orders+ --resource-type model
```

Second command returns `stg_orders`, `order_items`, `orders`, `customers`.

Recovery: if docs are not generated, `dbt docs generate` takes about 30 seconds on the Warehouse; otherwise talk over
the static lineage view in the Fabric dbt job item.

## Demo 4 · Fabric Lakehouse (Spark) · Change the engine (44:00-49:00)

```powershell
..\.venv-lakehouse\Scripts\Activate.ps1
dbt build --target lakehouse
```

Same files, `--target lakehouse`. Open `target\compiled\jaffle_shop\models\marts\customers.sql` and compare with the
Warehouse version (relation names, `coalesce(... , false)` instead of `cast(... as bit)`). Query in a notebook or the
SQL analytics endpoint:

```sql
select customer_type, count(*), sum(lifetime_spend) from LH_Jaffle_Shop.jaffle_shop.customers group by customer_type
```

Same numbers as Demo 1.

Recovery: if the Livy session takes more than 20 seconds to start, play the recording and keep talking about the
compiled SQL diff. `reuse_session: true` keeps the session between commands, so the warm-up run before the talk matters.

## Demo 5 (optional) · Fabric SQL database (from the discussion slot)

```powershell
..\.venv-sqldb\Scripts\Activate.ps1
dbt debug --target sqldb
dbt build --target sqldb
```

Same numbers. Say out loud: dbt-sqlserver targets Azure SQL; it builds this project on the Fabric SQL database in
rehearsal, but the adapter is not certified for it.

## Other hosts (show, do not run live)

- **Azure DevOps**: open the last pull-request pipeline run; point at the `ci_<id>` schema name in the log, the
  published artifact, and the "Drop CI schema" step.
- **Fabric dbt job**: open `DBT_Jaffle_Shop_WH`, show the GitHub source, the Output tab of the last run and the
  Lineage view.
- **Fabric notebook**: open `NB_dbt_Runner`, show the parameters cell and the exit value of the last run.

## After the talk

`..\tools\scenario.ps1 status` and `git status` must be clean. Drop any `dev_*` or `ci_*` schemas left behind:
`dbt run-operation drop_schema_if_exists --args "{schema_name: ci_local}"`.
