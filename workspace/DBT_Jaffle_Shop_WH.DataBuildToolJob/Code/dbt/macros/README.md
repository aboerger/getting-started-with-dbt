# `macros/` — SQL you can call

A **macro** is a function that returns SQL text. Macros are written in [Jinja](https://jinja.palletsprojects.com/),
the same templating language you see inside models, and they run at *compile* time — before a single
statement reaches the engine.

If stored procedures with dynamic SQL are your reference point, macros are the same idea with the
danger removed: the output is generated, reviewed as a diff, and written to `target/compiled/` where
you can read exactly what was produced, but the generation happens on your machine rather than inside
the database.

```
{{ cents_to_dollars('subtotal') }}          in stg_orders.sql
        │  dbt compile
        ▼
cast(subtotal / 100.0 as numeric(16, 2))    in target/compiled/.../stg_orders.sql
```

## What is here

| File | Purpose | Kind |
| --- | --- | --- |
| [`cents_to_dollars.sql`](cents_to_dollars.sql) | integer cents to a 2-decimal dollar amount | plain helper + per-engine variants |
| [`booleans.sql`](booleans.sql) | `to_bool()` and `is_true()` — booleans on engines that have no boolean type | per-engine variants |
| [`tsql_overrides.sql`](tsql_overrides.sql) | replaces two macros that ship *inside dbt and dbt_utils*, on the T-SQL engines only | override |
| [`generate_schema_name.sql`](generate_schema_name.sql) | decides which schema every model is built in | override of a dbt hook |
| [`drop_schema_if_exists.sql`](drop_schema_if_exists.sql) | an administrative task CI calls directly | operation |

Start with `cents_to_dollars.sql`; it is nine lines and shows the whole mechanism.

## Why macros exist here: one project, three engines

The three targets in [`../profiles.yml`](../profiles.yml) speak two dialects. T-SQL has no boolean
type and calls the decimal type `numeric`; Spark SQL has booleans and calls it `decimal`. Without
macros this project would need two copies of every model, and they would drift apart within a month.

**Dispatch** is how one call picks the right SQL per engine. The pattern is always three parts:

1. A macro whose only job is to hand off to the right implementation, by calling
   `adapter.dispatch('cents_to_dollars')`.
2. A `default__cents_to_dollars` implementation, used by any engine that has no specific one.
3. Per-engine implementations named with the adapter's prefix: `fabric__`, `sqlserver__`,
   `spark__`, `snowflake__`, and so on.

At compile time dbt looks for `<adapter>__<name>`, and falls back to `default__<name>` if there
isn't one. So `{{ cents_to_dollars('subtotal') }}` in a model becomes `numeric(16, 2)` when the target
is the Warehouse and `decimal(16, 2)` when it is the Lakehouse, and the model file never mentions
either engine. That is the whole trick behind Demo 4.

`booleans.sql` uses the same mechanism for a harder difference. T-SQL cannot put a boolean *expression*
in a `select` list at all, so `to_bool()` wraps it in `case when ... then 1 else 0 end` and casts to
`bit`, while the Spark version is just `coalesce(expr, false)`. And because a `bit` cannot be used as
a predicate either, `is_true()` renders `col = 1` on T-SQL and plain `col` on Spark. Two tiny macros,
and `products.sql` and `orders.sql` stay dialect-free.

## Overriding dbt's own macros

Nearly all of dbt's behaviour — how a table is created, how a test is rendered, how a schema is named
— is itself written as macros, and any of them can be replaced by defining a macro of the same name in
your project. Your project wins: dbt searches the root project first.

That is a genuinely powerful escape hatch, and this project needs it twice, for real bugs found while
porting to Fabric. [`tsql_overrides.sql`](tsql_overrides.sql) documents both in full:

- `dbt_utils.expression_is_true` renders a test query the T-SQL adapters wrap in a CTE, and a CTE
  column needs a name in T-SQL. The override adds one.
- The adapters' `date_trunc` implementation rounds `23:59:59.9999` *up* into the next day. The
  override casts to `date` instead. The unit test on `stg_locations` is what caught it.

Two things worth knowing before you reach for this yourself. First, you can override macros belonging
to a package (`dbt_utils`) as well as dbt's own. Second, a dispatched macro executes in the calling
package's namespace, so it cannot see other macros from your project — which is why the overrides in
that file are deliberately written to be self-contained rather than sharing a helper.

## Special macro names

Two macros in this folder are never called from a model. dbt calls them itself, by name:

- **`generate_schema_name`** is a hook dbt invokes for every node to decide its schema. The version
  here sends seeds to a shared `raw` schema and everything else to the target's schema. Replacing this
  one macro is how a project implements its environment strategy.
- **`drop_schema_if_exists`** is an *operation* — a macro invoked from the command line rather than
  from a model:

  ```powershell
  dbt run-operation drop_schema_if_exists --args "{schema_name: ci_1234}" --target ci
  ```

  The CI pipeline builds into a throwaway schema and calls this at the end to clean up. Operations are
  the right home for administrative SQL that is not a model.

## Reading and debugging macros

Macros are the one part of dbt where the code you write and the code that runs are not the same text,
so build the habit early:

```powershell
dbt compile --select stg_products
code ..\target\compiled\jaffle_shop\models\staging\stg_products.sql
```

Useful when writing one:

- Jinja comments are written between `{#` and `#}` and are stripped at compile time, so they never
  reach the database. The comment blocks at the top of each file in this folder are exactly that.
- `{{ log("...", info=True) }}` prints to the console during a run.
- Whitespace matters in generated SQL; a hyphen just inside a Jinja tag's delimiters trims the
  whitespace next to it, which is why the macro bodies in this folder are peppered with them.
- `{{ target.type }}`, `{{ target.name }}` and `{{ target.schema }}` tell a macro where it is running.
