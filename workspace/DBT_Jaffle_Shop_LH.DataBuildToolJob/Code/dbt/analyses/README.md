# `analyses/` — SQL that gets compiled but never run

This folder is empty, and it holds the least-known useful corner of dbt.

An **analysis** is a `.sql` file that dbt templates and compiles like a model, but never executes and
never materialises. `dbt compile` renders it to `target/compiled/jaffle_shop/analyses/`, and that is
the end of dbt's involvement — you take the resulting SQL and run it yourself.

## Why that is useful

Ad-hoc SQL has nowhere good to live. It ends up in a Slack message, a `scratch.sql` on somebody's
desktop, or a Power BI query nobody can find later. An analysis gives it a home in the repository,
with three advantages over a text file:

- It can use `{{ ref() }}` and `{{ source() }}`, so it keeps working when schemas or environments
  change, and it never hard-codes `jaffle_shop.customers`.
- It can use the project's macros, so a query written for the Warehouse compiles for the Lakehouse too.
- It is reviewed in a pull request like everything else.

Typical residents: the query behind a one-off board metric, a data-validation investigation, a
migration script, a "how do we reproduce last quarter's number" query.

## What one looks like

`analyses/customer_type_summary.sql` — the Demo 1 query, if it lived here:

```sql
-- The headline number: how much of lifetime spend comes from repeat customers?
select
    customer_type,
    count(*) as customers,
    sum(lifetime_spend) as lifetime_spend
from {{ ref('customers') }}
group by customer_type
```

Then:

```powershell
dbt compile --select analysis:customer_type_summary
code ..\target\compiled\jaffle_shop\analyses\customer_type_summary.sql
```

The compiled file has `jaffle_shop.customers` in place of the `ref`, ready to paste into the Fabric
query editor.

## Analysis, model, or test?

| Put it in | When |
| --- | --- |
| `models/` | something downstream should be able to build on the result |
| `analyses/` | a human reads the answer once, or occasionally |
| `data-tests/` | the answer should always be "no rows", and the build should fail if it is not |

The distinction is about ownership, not complexity. The moment two people need the same analysis
regularly, it should become a model — and promoting it is just moving the file.
