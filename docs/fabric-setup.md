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
| `NB_dbt_Runner` | Python notebook | "run dbt from a notebook" host |
| `DBT_Jaffle_Shop_WH` / `_LH` / `_DB` | dbt job (GitHub-sourced) | "run dbt as a Fabric job" host |

Collect the connection values for `tools/env.ps1`:

- **Warehouse host**: Warehouse -> Settings -> *SQL connection string*.
- **Lakehouse id**: the GUID after `/lakehouses/` in the Lakehouse URL, or
  `fab get "/<workspace name>.Workspace/LH_Jaffle_Shop.Lakehouse" -q id`.
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

## 7. Laptop

```powershell
winget install astral-sh.uv Microsoft.AzureCLI      # once
.\tools\setup-env.ps1                               # three pinned venvs
Copy-Item tools\env.example.ps1 tools\env.ps1        # then fill in the values
az login
```

Behind a TLS-inspecting corporate proxy, Python needs the corporate root CA: export the Windows
root store to a PEM (append it to `certifi`'s bundle) and set `REQUESTS_CA_BUNDLE` to that file
before running `dbt deps`, `dbt build --target lakehouse` (Livy API) or anything using azure-identity.
