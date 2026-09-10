# `data-tests/` — hand-written test queries

This folder is empty on purpose. It is worth understanding *why* it is empty, because that explains how
testing in dbt works.

## A dbt test is a `select` statement that should return nothing

That is the entire mechanism. dbt runs a query; **if it returns rows, the test fails**, and the rows it
returned are the failure. There is no assertion library and no special test runner — a test is SQL, and
you can paste it into a query window when it fails.

There are two ways to write one.

### 1. Generic tests — the ones in the `.yml` files

A generic test is a parameterised test you attach to a column or a model by name. This project has 33
of them, all declared in YAML beside the models:

```yaml
columns:
  - name: customer_id
    data_tests:
      - not_null
      - unique
```

Four generic tests ship with dbt itself — `unique`, `not_null`, `accepted_values` and `relationships`
(a foreign-key check) — and packages add more. This project uses `dbt_utils.expression_is_true` from
[dbt_utils](../packages.yml) for the arithmetic reconciliations, such as
`order_total - tax_paid = subtotal` on `stg_orders`.

Generic tests cover the overwhelming majority of real assertions, which is why they are declared in
YAML rather than written out: `unique` on a key is the same query every time, so you name it instead of
retyping it. Read the generated SQL any time with:

```powershell
dbt compile --select stg_orders
code ..\target\compiled\jaffle_shop\models\staging\stg_orders.yml\
```

### 2. Singular tests — the ones that would live here

Sometimes an assertion is specific to one situation and not worth parameterising. Then you write the
query yourself, as a `.sql` file in this folder, and dbt treats the file as a test node.

Any `.sql` file dropped in here becomes a test named after the file. For example
`data-tests/assert_no_future_orders.sql`:

```sql
-- Fails if any order is dated in the future.
select
    order_id,
    ordered_at
from {{ ref('stg_orders') }}
where ordered_at > current_date
```

No YAML entry, no registration step — the file *is* the test. Note the `{{ ref() }}`: a test is a
node in the DAG like any other, so dbt knows to run it after `stg_orders` is built, and it is included
when you select `stg_orders+`.

This project has none because every assertion it needs was expressible as a generic test. That is the
normal outcome, and the reason this folder ships empty in most dbt projects.

## Where unit tests fit

There is a third kind of test in this project, and it is a different tool for a different job.

| | Data tests (this folder, and the `.yml` files) | Unit tests |
| --- | --- | --- |
| Question answered | "is the data in the warehouse correct?" | "is the SQL logic correct?" |
| Input | whatever is really in the tables | fixed rows you write in the YAML |
| Needs data loaded | yes | no |
| Catches | a bad load, an upstream change, a broken assumption | a mistake in a `case` expression or a join |

Unit tests are declared in `unit_tests:` blocks in the model YAML — there are three in this project,
in [`../models/staging/stg_locations.yml`](../models/staging/stg_locations.yml),
[`../models/marts/orders.yml`](../models/marts/orders.yml) and
[`../models/marts/order_items.yml`](../models/marts/order_items.yml). Each supplies a handful of input
rows and states the exact output expected, so it can prove that a boolean converts correctly or that a
timestamp truncates to the right day without touching a single real record. The `date_trunc` bug
described in [`../macros/tsql_overrides.sql`](../macros/tsql_overrides.sql) was caught by one of them.

## Running tests

```powershell
dbt test                                   # every data test
dbt test --select stg_orders               # just this model's tests
dbt test --select test_type:unit           # just the unit tests
dbt build                                  # models and tests together, in dependency order
```

Prefer `dbt build`. It interleaves tests with the models, so when a test fails, the models downstream
of it are **skipped** instead of being built on top of data already known to be wrong — that is Demo 2,
and it is the difference between a broken pipeline and a broken report.

By default a failing test shows you a count. Add `--store-failures` and dbt writes the offending rows
to a table so you can query them.
