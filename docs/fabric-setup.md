# One-time setup: Fabric, Entra and Azure DevOps

Everything the demos need that is *not* code. Do this once; the runbook assumes it is done.

## 1. Fabric workspace items

The workspace `ad51bc60-66e8-45ac-9939-c54f343f54ce` is Git-connected to this repository
(folder `workspace/`). It already contains:

| Item | Type | Used by |
| --- | --- | --- |
| `WH_Jaffle_Shop` | Warehouse | target `warehouse` / `ci`, Demos 1-3 |
| `LH_Jaffle_Shop` | Lakehouse (schema-enabled) | target `lakehouse`, Demo 4 |
| `DB_Jaffle_Shop` | SQL database | target `sqldb`, Demo 5 |
| `NB_dbt_Runner` | Python notebook (3.11 kernel) | "run dbt from a notebook" host, all three targets (Warehouse over TDS, Lakehouse over Livy, SQL database); code and dbt stack from the published bundle `Files/dbt/jaffle_shop_python.zip` in `LH_Jaffle_Shop` |
| `NB_dbt_Runner_Spark` | PySpark notebook | Lakehouse only, dbt-fabricspark `method: session` in the notebook's own Spark session; code and dbt stack from the published bundle `Files/dbt/jaffle_shop.zip` in `LH_Jaffle_Shop` |
| `DBT_Jaffle_Shop_WH` / `_LH` / `_DB` | dbt job (project synced into the item by `tools/sync_fabric_dbt_jobs.py`) | "run dbt as a Fabric job" host |

Collect the connection values for `tools/env.ps1`:

- **Warehouse host**: Warehouse -> Settings -> *SQL connection string*.
- **Lakehouse id**: the GUID after `/lakehouses/` in the Lakehouse URL, or
  `fab get "/External Demos - dbt.Workspace/LH_Jaffle_Shop.Lakehouse" -q id` (the workspace display
  name; keep every `fab` path inside this workspace).
- **SQL database host and name**: SQL database -> Settings -> *Connection strings*. The database name has
  the form `DB_Jaffle_Shop-<item id>`.

## 2. Tenant settings (Fabric admin portal)

- **dbt jobs (preview)** enabled for the tenant or your security group.
- **Service principals can use Fabric APIs** enabled (needed by CI and by the Lakehouse job).
- Git integration enabled (already in use).

## 3. Service principal for automation

Used by Azure DevOps (`--target ci`) and by the SQL database dbt job (its Azure SQL adapter only
offers Basic or service-principal authentication).

1. Entra ID -> App registrations -> **New registration** (for example `sp-dbt-jaffle-shop`).
   Note the *Application (client) ID* and *Directory (tenant) ID*.
2. Certificates & secrets -> **New client secret**. Copy the value once.
3. Fabric workspace -> Manage access -> add the app as **Contributor**.
4. Nothing else is needed: Contributor grants read/write on the Warehouse, Lakehouse and SQL database.

The profile uses `authentication: environment`, so the pipeline passes the three values as
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`.

Two things learned the hard way:

- **Lakehouse target**: dbt-fabricspark talks to the Fabric REST API (Livy). A service principal gets
  `403 Forbidden` on `.../livyapi/...` until the tenant setting **Service principals can use Fabric APIs**
  includes it (a Contributor role alone is not enough). Interactive users need `az login` and
  `DBT_SPARK_AUTH=CLI` instead.
- **SQL database target**: a workspace-role identity (user or service principal) is not a database user, so
  `CREATE SCHEMA [raw]` fails with "Principal ... could not be resolved. Server identity is not configured".
  The `sqldb` output therefore sets `schema_authorization: dbo`, which makes dbt-sqlserver run
  `CREATE SCHEMA [raw] AUTHORIZATION [dbo]`.

## 4. Azure DevOps

1. Create a project and a pipeline from **GitHub** -> this repository -> existing YAML file
   `azure-pipelines.yml`. Azure DevOps creates the GitHub service connection during this step.
2. Library -> **Variable group** `dbt-fabric` with:

   | Variable | Value |
   | --- | --- |
   | `DBT_WAREHOUSE_HOST` | the Warehouse SQL connection string host |
   | `DBT_FABRIC_WORKSPACE_ID` | `ad51bc60-66e8-45ac-9939-c54f343f54ce` |
   | `AZURE_TENANT_ID` | tenant id |
   | `AZURE_CLIENT_ID` | app (client) id |
   | `AZURE_CLIENT_SECRET` | client secret (lock icon = secret) |

3. Pipelines -> the pipeline -> ... -> **Security** -> allow the variable group.
4. Open a pull request that touches `jaffle_shop/`; the pipeline builds into `ci_<build id>`,
   publishes `target/` as an artifact and drops the schema.

Microsoft-hosted agents can reach Fabric, so no self-hosted agent is needed.

You can rehearse the pipeline steps from a laptop before Azure DevOps exists (verified 2026-09-09: 48/48 in 35 s,
schema dropped afterwards):

```powershell
. .\tools\env.ps1; $env:BUILD_BUILDID = 'local'      # AZURE_* values set, DBT_AUTH not needed for ci
cd jaffle_shop
dbt build --target ci                                 # builds into WH_Jaffle_Shop.ci_local
dbt run-operation drop_schema_if_exists --args "{schema_name: ci_local}" --target ci
```

## 5. Fabric dbt jobs: the project synced into the items

The dbt job items `DBT_Jaffle_Shop_WH` / `_LH` (and `_DB`) run the project as their **own code**
(`projectType: OneLake`, the mode a new dbt job starts in). The code still exists once, in `jaffle_shop/`:
`tools/sync_fabric_dbt_jobs.py` copies it into each item's `Code/dbt/` folder under `workspace/`, Fabric's
Git integration carries that folder into the item, and CI runs the script with `--check`, so a pull request
whose copies are stale fails. What travels with the copy and what does not:

- `dbt_packages/` from `dbt deps`, trimmed to `dbt_project.yml` + `macros/` per package. The job editor
  says package dependencies are not supported (the runtime does not run `dbt deps`), so vendoring them is
  what makes `dbt_utils` resolve - the same trick the notebook bundles use.
- Not copied: `seeds/` (seeds are disabled in the jobs; the raw tables are loaded once, separately, and the
  CSVs are 16 MB), `profiles.yml` (Fabric generates the profile from the item's connection), `target/`,
  `logs/`, `.user.yml`, `.gitignore`. A `GENERATED.md` in the copy says where it came from.

Why not the GitHub-connected job mode: it was tried on 2026-09-10 and could not be made to run this
project. With the project in `jaffle_shop/` every run failed with `20418: The project yaml file was not
found in the dbt project` (the wizard has no project-path field; the `folderPath` in the item definition
was verified through the REST API to change nothing), and with a generated branch that had the project at
the root, with or without the large seeds, it failed with `20407: Failed to download dbt project from
GitHub repository`, with no log of what it choked on. The item-owned project is the mode the sample job
ships in and it ran here before.

1. Workspace -> **+ New item** -> **dbt job** -> name `DBT_Jaffle_Shop_WH`. Do **not** connect a GitHub
   project; the empty project is fine, the sync fills it.
2. Adapter and connection:

   | Job | Adapter | Connection | Schema | Notes |
   | --- | --- | --- | --- | --- |
   | `DBT_Jaffle_Shop_WH` | Fabric Data Warehouse | `WH_Jaffle_Shop` | `jaffle_shop` | seed data **off** |
   | `DBT_Jaffle_Shop_LH` | Fabric Lakehouse | `LH_Jaffle_Shop` | `jaffle_shop` | seed data **off** |
   | `DBT_Jaffle_Shop_DB` | Azure SQL Database | server + database of `DB_Jaffle_Shop`, service principal from step 3 | `jaffle_shop` | evaluation path, not certified |

3. Command **build**, threads 4. Save. Workspace -> Source control -> **Commit**, so the item definition
   (`workspace/DBT_Jaffle_Shop_WH.DataBuildToolJob/dbt-content.json` + `.platform`) lands in this
   repository; pull it.
4. From `.venv-tools`: `python tools\sync_fabric_dbt_jobs.py` (or the VS Code task **Sync dbt project into
   Fabric dbt job items**). It rewrites `Code/dbt/` in every `workspace/DBT_*.DataBuildToolJob` and sets the
   item's project to `OneLake` / `dbt`. Commit, push, then Workspace -> Source control -> **Update**.
5. **Run** the job; check the Output and Lineage tabs.
6. After every change to `jaffle_shop/`: run the sync again and commit the copies (CI reminds you when
   they are stale). The dbt job runtime's adapters are older than the laptop's (dbt-fabric 1.10.0,
   dbt-fabricspark 1.12.2, dbt-sqlserver 1.9.1 on dbt Core 1.11), which is fine for this project.

Seeds are disabled in `dbt_project.yml` unless `load_source_data` is set, so leaving the job's
*Seed data* option off is belt and braces: `dbt build` inside Fabric never reloads the raw tables.
Load them once from the laptop or the notebook (`load_source_data = "true"`).

## 6. Runner notebooks: the published-bundle pattern

Two notebooks run dbt on Fabric. Neither fetches the project from GitHub or `pip install`s from PyPI at
run time; each installs **one published zip** from `LH_Jaffle_Shop`, the way the AANA Hub's Gold layer
runs in production. The zip carries the dbt project with `dbt_packages/` vendored, the adapter(s), a fresh
`jaffle-dbt-runner` wheel from `runner/`, and *only those wheels the notebook's runtime does not already
ship*, resolved at publish time against Microsoft's manifest of that runtime (`tools/runtime_constraints/`).

| notebook | kind | bundle (`tools/publish_dbt_bundle.py`) | runtime manifest | targets |
| --- | --- | --- | --- | --- |
| `NB_dbt_Runner` | Python, **Python 3.11 kernel** | `--runner python` -> `Files/dbt/jaffle_shop_python.zip` (dbt-fabric + dbt-fabricspark + dbt-sqlserver) | `python-3.11`: the "Jupyter 1.0" image release note, `# Python3.11` table | `warehouse`, `lakehouse` (Livy), `sqldb` |
| `NB_dbt_Runner_Spark` | PySpark, Spark **Runtime 2.0** | `--runner spark` -> `Files/dbt/jaffle_shop.zip` (dbt-fabricspark only) | `2.0`: `Fabric-Python313-CPU.yml` | `lakehouse_session` |

1. **Publish the bundle(s)** (once per code change, from the laptop or CI/CD):

   ```powershell
   .\tools\setup-env.ps1 -Target tools                       # .venv-tools = lakehouse stack + publish tooling
   .\.venv-tools\Scripts\Activate.ps1
   python tools\publish_dbt_bundle.py --runner python --workspace "<workspace name or GUID>"   # NB_dbt_Runner
   python tools\publish_dbt_bundle.py --runner spark  --workspace "<workspace name or GUID>"   # NB_dbt_Runner_Spark
   ```

   Or the VS Code tasks **Publish Lakehouse bundle (Python runner)** / **(Spark runner)** (Terminal -> Run
   Task), which prompt for the workspace and use `.venv-tools` directly. The script runs `dbt deps` so
   `dbt_packages/` travels in the zip, builds the runner wheel, resolves the adapter pins from
   `requirements/*.in` for the runtime's Python (3.11 or 3.13, manylinux) against the runtime manifest,
   downloads only the wheels the runtime lacks, and uploads the zip plus a sidecar `deployment.json`. It
   prints what it shipped, what it pruned and which runtime packages it replaces, each with its reason:
   - Python notebook: `azure-core` 1.29.4 -> 1.41 and `azure-identity` 1.17 -> 1.25 (dbt-fabric's
     `azure.identity` imports `AccessTokenInfo`, the ImportError the pip-at-run-time notebook died with),
     `pyodbc` 4.0 -> 5.3 (dbt-sqlserver needs >= 5.2; the image's ODBC Driver 18 serves both).
   - Spark notebook: `protobuf` (pinned 6.31.1), `opentelemetry-api`, `pathspec`.

   Authentication: service-principal env vars if set, else `az login`, else a browser sign-in cached for
   later runs. TLS trusts the Windows certificate store (`truststore`), so the corporate proxy needs no
   extra setup. `--assemble-only` builds the zip without authenticating; CI does that for both bundles on
   every PR.
2. **Match the runtime.** The Python notebook's metadata selects the **Python 3.11** kernel (the image
   offers 3.10/3.11/3.12; the bundle is resolved for 3.11). The workspace's Spark runtime must be **2.0**
   (Workspace settings -> Data Engineering/Science -> Spark settings -> Environment -> Runtime version) for
   the Spark notebook. On any other Python the bootstrap stops with a message naming the mismatch and the
   `--runtime` fix.
3. **Run the notebook.** Both bind `LH_Jaffle_Shop` as the default lakehouse **by name** in a
   `%%configure` cell, so no workspace GUID is stored and the notebook is correct in any workspace that has
   that lakehouse. The bootstrap cell copies the zip to the kernel's disk and installs `wheels/` offline
   (`pip install --no-index --no-deps --target`, never `%pip`); the last cell calls
   `jaffle_dbt_runner.run_project()`. Set the parameters cell (`target`, `command`, `select`, connection
   values) and run; from a pipeline, use a Notebook activity and override the same parameters. The notebook
   exits with a JSON outcome (`success`, `statuses`, `elapsed_seconds`, `deployed_commit`, ...) that the
   pipeline can branch on.

Authentication in `NB_dbt_Runner` is the notebook identity throughout: dbt-fabric's
`authentication: notebookutils` for the Warehouse, dbt-fabricspark's `fabric_notebook` for the Lakehouse
over Livy, and for the SQL database an access token the runner fetches with
`notebookutils.credentials.getToken` and passes to dbt-sqlserver as `ActiveDirectoryAccessToken` through
the `DBT_SQLDB_ACCESS_TOKEN` variables in `profiles.yml` (static for the run; the build takes ~1 min).
`NB_dbt_Runner_Spark` needs no credentials at all: dbt attaches to the notebook's own Spark session.

Details worth knowing:

- **Why the Python notebook moved to the bundle.** Its previous version ran
  `pip install -r requirements/<target>.txt` on the kernel. pip upgraded azure-core on disk, but in a Python
  notebook `pip` never restarts the kernel, and the kernel had already imported the image's azure-core
  1.29.4 for `notebookutils` before the first cell ran; dbt-fabric then failed with
  `cannot import name 'AccessTokenInfo' from 'azure.core.credentials'`. The bootstrap now installs into a
  private folder and, on the Python kernel only (`evict_shadowed=True`), drops the pre-imported modules the
  bundle shadows from `sys.modules`, so dbt imports the bundle's azure-core. Nothing in the image's
  site-packages is modified.
- **Manifest drift.** Microsoft publishes the Python-notebook image's package list as release notes
  (`Fabric/Jupyter 1.0/*.md` in `microsoft/synapse-spark-runtime`), one table per kernel, with upgraded
  entries written `old -> new`; the constraints take the *new* version (what the release ships, e.g.
  protobuf 6.33.6). The bootstrap compares every pruned package with the kernel's actual version and prints
  a `WARNING` per mismatch. If dbt then fails to import, run
  `python tools\refresh_runtime_constraints.py --runtime python-3.11` (it picks the newest release note)
  and republish.
- With `method: session` (Spark notebook) there is no REST API, so the adapter infers "schema-enabled"
  from `schema != lakehouse` and resolves three-part names (`LH_Jaffle_Shop.jaffle_shop.customers`)
  against the session's default catalog; the runner rejects `schema == lakehouse_name` up front. The Livy
  target in the Python notebook asks the Fabric API instead and needs the lakehouse and workspace ids
  (defaulted from the bound lakehouse).
- Parameters (strings, so a pipeline Notebook activity can set them): `command`, `select`, `exclude`,
  `full_refresh`, `threads` (empty = the profile's 4), `load_source_data`, `dbt_extra_args` (JSON list),
  `schema`, `lakehouse_name`, `bundle_zip`, `dbt_log_path`, `dbt_log_level`, `dbt_log_level_file`; the
  Python notebook adds `target`, `warehouse_host`, `warehouse_name`, `lakehouse_id`, `sqldb_host`,
  `sqldb_name`.
- `dbt.log`, `run_results.json` and `manifest.json` are uploaded to `Files/dbt-logs/` in the lakehouse
  after every run, dbt.log even when dbt fails. A dbt failure raises, so the Notebook activity fails.
- `deployment.json` inside the zip is the answer to "which code did that run use?": commit, publish time,
  consumer notebook, runtime, and the wheels shipped/pruned/replaced. The notebook prints it at start.
- Why not `pip install` on the driver, as the Spark notebook once did? pip re-solves against whatever the
  runtime preinstalled and upgrades shared packages in place; dbt's `protobuf>=6` requirement lands on
  6.33.x, which Runtime 2.0 tolerates only up to 6.31.1 - sessions built that way die at kernel start
  with no useful error. Resolving at publish time against the vendored manifest turns that into a loud
  publish failure unless the replacement is allow-listed with a reason.
- The `lakehouse_session` output requires PySpark at profile-parse time, so it is unusable from the
  laptop venvs by design. Keep using `--target lakehouse` (Livy) there and for speed comparisons.
- When Microsoft updates a runtime: `python tools\refresh_runtime_constraints.py --runtime 2.0` and
  `--runtime python-3.11` regenerate the constraints files (headers record the manifest hash), then
  republish. The VS Code task **Refresh Fabric runtime constraints** runs both.

## 7. Laptop

```powershell
winget install astral-sh.uv Microsoft.AzureCLI      # once; open a new terminal afterwards so az is on PATH
.\tools\setup-env.ps1                               # three pinned venvs
Copy-Item tools\env.example.ps1 tools\env.ps1        # then fill in the values
az login
```

Without `az login` you can still run everything as the service principal: set `DBT_AUTH=environment`
and `DBT_SPARK_AUTH=SPN` in `tools/env.ps1` next to the `AZURE_*` values.

Behind a TLS-inspecting corporate proxy, Python needs the corporate root CA: export the Windows
root store to a PEM (append it to `certifi`'s bundle) and set `REQUESTS_CA_BUNDLE` to that file
before running `dbt deps`, `dbt build --target lakehouse` (Livy API) or anything using azure-identity.
The bundle tooling (`tools\publish_dbt_bundle.py`, `refresh_runtime_constraints.py`) does not need this: it
trusts the operating system's certificate store through `truststore`, and pip does the same by default.
