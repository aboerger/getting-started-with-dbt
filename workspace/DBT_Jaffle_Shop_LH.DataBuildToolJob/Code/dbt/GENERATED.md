# Generated copy, do not edit

This folder is `jaffle_shop/` copied by `tools/sync_fabric_dbt_jobs.py` so the Fabric dbt job item runs it as its own project (`projectType: OneLake`). `dbt_packages/` is the resolved `dbt deps` output, trimmed to what dbt loads at run time; `seeds/` and `profiles.yml` are left out on purpose (seeds are disabled in the jobs, Fabric generates the profile). Change the project on `main`, then run the sync; CI fails a pull request whose copies are stale (`--check`).
