# `snapshots/` — history for data that gets overwritten

This folder is empty, but the concept it holds answers a question that comes up in every dbt
introduction: *what happens when the source system updates a row in place?*

## The problem

`raw_customers` has one row per customer. If a customer moves from Vice City to San Andreas, ingestion
overwrites the row, and the previous value is gone — from the source, and therefore from every model
downstream of it. Next month's report cannot reproduce last month's number, and nobody can answer "how
many customers were in Vice City in March?"

Rebuilding models does not help. `customers` is a `create table as select` over whatever the source
says *today*.

## What a snapshot does

A **snapshot** is a table dbt maintains that records how a row changed over time — a Type 2
slowly-changing dimension, built for you. On every `dbt snapshot` run, dbt compares the current source
rows against the snapshot table and, where a tracked column has changed, closes off the old record and
inserts a new one.

dbt adds the bookkeeping columns:

| Column | Meaning |
| --- | --- |
| `dbt_scd_id` | surrogate key for this version of the row |
| `dbt_valid_from` | when this version became current |
| `dbt_valid_to` | when it stopped being current — `null` for the row that is current now |
| `dbt_updated_at` | the timestamp dbt used for the comparison |

So `where dbt_valid_to is null` gives you today's picture, and
`where '2025-03-01' between dbt_valid_from and coalesce(dbt_valid_to, '9999-12-31')` gives you March's.

A snapshot is the one thing in dbt that is **stateful**: it is the only object you cannot rebuild from
the source, because the history it holds no longer exists anywhere else. That makes it the one thing in
a dbt project that must be backed up, and a good reason to keep snapshots thin and few.

## What one would look like here

Since dbt 1.9 a snapshot is defined in YAML, in a `.yml` file in this folder:

```yaml
snapshots:
  - name: customers_snapshot
    relation: source('ecom', 'raw_customers')
    config:
      unique_key: id
      strategy: check
      check_cols: [name]
```

Then `dbt snapshot` (or `dbt build`, which includes snapshots) maintains it, and models read it with
`{{ ref('customers_snapshot') }}` like any other node.

The two strategies are the whole design decision:

| Strategy | How it detects a change | Use when |
| --- | --- | --- |
| `timestamp` | an `updated_at` column in the source moved | the source has a reliable modified date — preferred, and cheaper |
| `check` | the values in `check_cols` differ from the stored version | there is no such column, as with `raw_customers` here |

Older projects define snapshots in `.sql` files wrapped in a snapshot block with a `config()` call
inside; you will meet that form in the dbt documentation and in existing repositories. Both work.

## Why this project has none

The Jaffle Shop source data is static, so there is no history to capture, and a snapshot would add a
stateful object to a demo whose whole point is that everything can be rebuilt from scratch in thirty
seconds. `snapshot-paths: ["snapshots"]` is still declared in [`../dbt_project.yml`](../dbt_project.yml),
so dropping a definition in here is all it would take.
