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
| `NB_dbt_Runner` | Python notebook | "run dbt from a notebook" host, all three targets over Livy / SQL |
| `NB_dbt_Runner_Spark` | PySpark notebook | Lakehouse only, dbt-fabricspark `method: session` in the notebook's own Spark session; code and dbt stack from the published bundle `Files/dbt/jaffle_shop.zip` in `LH_Jaffle_Shop` |
| `DBT_Jaffle_Shop_WH` / `_LH` / `_DB` | dbt job (GitHub-sourced) | "run dbt as a Fabric job" host |

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

## 5. Fabric dbt jobs from the GitHub repository

The job pulls the project from GitHub on every run, so the code exists once (in `jaffle_shop/`).
Repeat for the three targets.

1. Create a **classic** GitHub personal access token with `repo` scope (fine-grained tokens are not
   accepted at the time of writing).
2. Workspace -> **+ New item** -> **dbt job** -> name `DBT_Jaffle_Shop_WH` -> **Connect to a GitHub project**
   -> *GitHub - Source Control* -> repository `https://github.com/aboerger/getting-started-with-dbt`,
   connection name `github-getting-started-with-dbt`, paste the PAT.
3. Branch `main`; dbt project path `jaffle_shop`.
4. Adapter and connection:

   | Job | Adapter | Connection | Schema | Notes |
   | --- | --- | --- | --- | --- |
   | `DBT_Jaffle_Shop_WH` | Fabric Data Warehouse | `WH_Jaffle_Shop` | `jaffle_shop` | seed data **off** |
   | `DBT_Jaffle_Shop_LH` | Fabric Lakehouse | `LH_Jaffle_Shop` | `jaffle_shop` | seed data **off** |
   | `DBT_Jaffle_Shop_DB` | Azure SQL Database | server + database of `DB_Jaffle_Shop`, service principal from step 3 | `jaffle_shop` | evaluation path, not certified |

5. Command **build**, threads 4. Save, **Run**, check the Output and Lineage tabs.
6. Workspace -> Source control -> **Commit** so the item definitions land in `workspace/`, then pull
   this repository.

Seeds are disabled in `dbt_project.yml` unless `load_source_data` is set, so leaving the job's
*Seed data* option off is belt and braces: `dbt build` inside Fabric never reloads the raw tables.
Load them once from the laptop or the notebook (`load_source_data = True`).

## 6. Runner notebook

`workspace/NB_dbt_Runner.Notebook` syncs into the workspace through Git. Attach `LH_Jaffle_Shop`
as its default lakehouse (for the Lakehouse target and for the artifact copy), set the parameters
cell (`target`, `command`, `select`, connection values) and run. From a pipeline, use a Notebook
activity and override the same parameters; the notebook exits with a JSON summary that the
pipeline can branch on.

Authentication is the notebook identity: `notebookutils` for the Warehouse, `fabric_notebook` for
the Lakehouse, and an access token from `notebookutils.credentials.getToken` for the SQL database.

### 6b. Spark runner notebook (Lakehouse only): the published-bundle pattern

`workspace/NB_dbt_Runner_Spark.Notebook` is a **PySpark** notebook that uses the `lakehouse_session`
output of `profiles.yml` (dbt-fabricspark `method: session`). Instead of opening a Livy session over the
REST API, dbt calls `SparkSession.builder.getOrCreate()` and gets the notebook's own session, so every
statement runs as `spark.sql(...)` on the driver: no session start, no HTTP round trips, no credentials
and no ids in the profile. Unlike `NB_dbt_Runner`, it does **not** fetch the project from GitHub or
`pip install` from PyPI at run time. It installs one published zip, the way the AANA Hub's Gold layer
runs in production:

1. **Publish the bundle** (once per code change, from the laptop or CI/CD):

   ```powershell
   .\tools\setup-env.ps1 -Target tools                       # .venv-tools = lakehouse stack + publish tooling
   .\.venv-tools\Scripts\Activate.ps1
   python tools\publish_dbt_bundle.py --workspace "<workspace name or GUID>"
   ```

   Or run the VS Code task **Publish Lakehouse bundle** (Terminal -> Run Task), which prompts for the
   workspace and uses `.venv-tools` directly. The script runs `dbt deps` so `dbt_packages/` travels in the zip, builds a fresh `jaffle-dbt-runner`
   wheel from `runner/`, resolves `requirements/lakehouse.in` (dbt-core 1.11 + dbt-fabricspark 1.13.4)
   for Runtime 2.0's Python 3.13 against the runtime's package manifest (`tools/runtime_constraints/`),
   downloads only the wheels the runtime lacks, and uploads `Files/dbt/jaffle_shop.zip` plus a sidecar
   `deployment.json` to `LH_Jaffle_Shop`. It prints what it shipped, what it pruned and which runtime
   packages it replaces (`protobuf`, `opentelemetry-api`, `pathspec`, each with its reason). Authentication:
   service-principal env vars if set, else `az login`, else a browser sign-in cached for later runs.
   TLS trusts the Windows certificate store (`truststore`), so the corporate proxy needs no extra setup.
   `--assemble-only` builds the zip without authenticating; CI does that on every PR.
2. **Set the workspace Spark runtime to 2.0** (Workspace settings -> Data Engineering/Science -> Spark
   settings -> Environment -> Runtime version). The bundle's wheels target that runtime's driver Python;
   on any other runtime the bootstrap stops with a message naming the mismatch and the `--runtime` fix.
3. **Run the notebook.** Its `%%configure` cell binds `LH_Jaffle_Shop` as the default lakehouse **by
   name**, so no workspace GUID is stored and the notebook is correct in any workspace that has that
   lakehouse. The bootstrap cell copies the zip to the driver and installs `wheels/` offline
   (`pip install --no-index --no-deps --target`, never `%pip`, which would restart the interpreter and is
   disabled in pipeline runs); the last cell calls `jaffle_dbt_runner.run_project()`.

Details worth knowing:

- With no REST API available the adapter infers "schema-enabled" from `schema != lakehouse` and resolves
  three-part names (`LH_Jaffle_Shop.jaffle_shop.customers`) against the session's default catalog. The
  runner rejects `schema == lakehouse_name` up front.
- Parameters (strings, so a pipeline Notebook activity can set them): `command`, `select`, `exclude`,
  `full_refresh`, `threads` (empty = the profile's 4), `load_source_data`, `dbt_extra_args` (JSON list),
  `schema`, `lakehouse_name`, `bundle_zip`, `dbt_log_path`, `dbt_log_level`, `dbt_log_level_file`. The
  notebook exits with a JSON outcome (`success`, `statuses`, `elapsed_seconds`, `deployed_commit`, ...).
- `dbt.log`, `run_results.json` and `manifest.json` are uploaded to `Files/dbt-logs/` in the lakehouse
  after every run, dbt.log even when dbt fails. A dbt failure raises, so the Notebook activity fails.
- `deployment.json` inside the zip is the answer to "which code did that run use?": commit, publish time,
  runtime, and the wheels shipped/pruned/replaced. The notebook prints it at start.
- Why not `pip install` on the driver, as the notebook did before? pip re-solves against whatever the
  runtime preinstalled and upgrades shared packages in place; dbt's `protobuf>=6` requirement lands on
  6.33.x, which Runtime 2.0 tolerates only up to 6.31.1 - sessions built that way die at kernel start
  with no useful error. Resolving at publish time against the vendored manifest turns that into a loud
  publish failure unless the replacement is allow-listed with a reason.
- The `lakehouse_session` output requires PySpark at profile-parse time, so it is unusable from the
  laptop venvs by design. Keep using `--target lakehouse` (Livy) there and for speed comparisons.
- When Microsoft updates the runtime: `python tools\refresh_runtime_constraints.py --runtime 2.0`
  regenerates the constraints file (the header records the manifest hash), then republish.

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
