(authentication)=

# Authentication and permissions

## Authentication

The engine delegates authentication to the Databricks SDK's [unified authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth) layer, so any mechanism the SDK supports will work.

```{list-table}
:header-rows: 1
:widths: 20 30 30

* - Mechanism
  - Required inputs
  - Typical use
* - Personal Access Token (PAT)
  - `DATABRICKS_HOST`, `DATABRICKS_TOKEN`
  - CI, scripted runs, GitHub Actions
* - OAuth M2M client credentials
  - `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`
  - Service principal automation
* - Azure service principal
  - `DATABRICKS_HOST`, `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`
  - Azure Databricks workspaces
* - CLI profile
  - `--profile <name>` plus matching entry in `~/.databrickscfg`
  - Local development
* - Default profile
  - `[DEFAULT]` section in `~/.databrickscfg` (no `--profile` flag needed)
  - Local development
* - Metadata service or managed identity
  - Runtime-supplied credentials
  - Databricks Apps, cluster-bound runs
```

### Precedence

Resolution precedence matches the SDK's unified-auth chain:

1. Explicit `--profile` flag
2. Environment variables
3. `~/.databrickscfg`
4. Metadata service

Omit `--profile` entirely to let the SDK pick whichever source is configured in the current environment.

## Required permissions

Whichever identity the engine authenticates as (typically a service principal for automation) must hold:

- **Workspace admin** on the target workspace: needed to fetch users, service principals, and groups from the account identity API
- **Metastore admin** on the target metastore: needed to create, alter, and manage catalogs, schemas, tables, volumes, functions, tags, grants, masks, and filters
- **Governed tag `creator` and `manager`** on the account: needed to create and update account-level governed tags (tag policies) under `resources.governed_tags`
- **`MANAGE DISCOVERY`**: needed when creating, updating, or deleting Discovery domains
- **Group `manager` on each managed group**: needed to add and remove members of the account groups under `resources.groups` when `--group-modification-scopes` is active. The engine automatically receives the `manager` role on any group it creates via `--group-creation-scopes`, so groups created by the engine are manageable without further grants. For pre-existing groups, the role must be granted to the engine principal out of band
