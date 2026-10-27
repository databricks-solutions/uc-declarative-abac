(policy-explorer)=

# ABAC Policy Explorer

ABAC Policy Explorer is a read-only Databricks App that shows who can see what under your deployed ABAC governance: which principals can read a table, which grants make that possible, and which column masks and row filters apply to them. Every step of an explanation links back to the config file that declares it.

It reads the tables written by {ref}`uc-abac dump <dumping-state>`, so it explains the state that is actually deployed in Unity Catalog, including grants made outside the config.

## What it shows

- **Access by principal**: the tables a user, service principal, or group can read, and the columns masked or rows filtered for them
- **Access by securable**: the principals that can read a table or see a column unmasked
- **Why**: for any principal and table or column, the chain from group membership through the tags and policies to the grants, masks, and filters that apply

Read access to a table requires `USE CATALOG`, `USE SCHEMA`, and `SELECT`, each granted on the securable itself or an ancestor. Each grant is explained by the grant policy that produces it, matched against the tags currently in Unity Catalog:

- A privilege that no grant policy produces (for example, a manual `GRANT`) is shown as a **manual grant**, apart from the ABAC grant policies.
- A privilege that a grant policy should produce but Unity Catalog does not hold (typically a config change not yet deployed) is reported as **drift** and is not counted as access.

In the access graph, ABAC grant policies, manual grants (dotted edges in their own colour), and drift (red dashed edges labelled with the expected privilege) are drawn differently, so you can see which access comes from the config. The warnings badge in the header lists every drift item; selecting one opens the graph of the affected principal with the path from the grant policy to the securable highlighted.

Ownership and admin roles are not modelled. A mask or filter condition the explorer cannot evaluate against tags (such as a context or identity attribute) is reported as a warning and never treated as matching, so the explorer can under-report access but never invent it.

## How it works

The app loads every dump table from the target schema when it starts, through a SQL warehouse, as the app's service principal. Run `uc-abac dump` after each deployment to keep the tables current, then refresh the app (`POST /api/refresh`, or restart it) to reload them.

```{figure} ../_static/policy-explorer-architecture.svg
:alt: Architecture of ABAC Policy Explorer. uc-abac deploy applies the YAML configs to Unity Catalog and uc-abac dump writes the deployed state to dump tables. The app reads the tables through a SQL warehouse, rebuilds and caches a model, and serves verdicts and graphs to a React UI over a REST API. The UI links back to the config files on GitHub.
:width: 100%

ABAC Policy Explorer components and data flows.
```

1. `uc-abac deploy` applies the YAML configs to Unity Catalog: tags, grants, ABAC policies, and groups.
2. `uc-abac dump` reads the deployed state back from Unity Catalog and writes it to tables in the target schema.
3. The app's dump reader runs a `SELECT` on each dump table through the SQL warehouse, as the app's service principal.
4. The model loader parses the rows (policies, tag conditions, group memberships), and matching reconciles each grant policy with the privileges Unity Catalog holds: each privilege is attributed to the policy that produces it, a manual grant, or drift. The model store caches the result as one model shared by every user.
5. The UI asks the REST API (`/api/*`) for verdicts and graphs, which are computed from the cached model on demand.
6. With `repo_slug` set, nodes and edges link to the config file on GitHub that declares them.

The backend lives in `src/abac_viewer/backend` (the engine in `engine/`, the API in `router.py`) and the UI in `src/abac_viewer/ui`. The explorer expands grant policies the way `uc-abac deploy` does, using the engine's privilege maps (`uc_abac.types`); its tests check this by simulating dumps with the engine's compilers. For how the explorer fits with the rest of the engine, see the [architecture overview](../getting-started/overview.md#architecture).

## Deploy it

The app is packaged as a Databricks Asset Bundle (`databricks.yml` in the repository root). Building it requires [`apx`](https://github.com/databricks-solutions/apx), [Bun](https://bun.sh/), and [`uv`](https://docs.astral.sh/uv/).

1. Dump the state behind your config into a target schema:

   ```bash
   uc-abac dump --config-dir ./configs --warehouse-id <warehouse-id> --target-schema main.uc_abac_state
   ```

2. Deploy the app from the repository root:

   ```bash
   databricks bundle deploy -t dev --var target_schema=main.uc_abac_state --var warehouse_id=<warehouse-id>
   ```

3. Grant the app's service principal read access to the dump tables. Its application ID is the `service_principal_client_id` returned by `databricks apps get abac-policy-explorer`:

   ```sql
   GRANT USE CATALOG ON CATALOG main TO `<application-id>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA main.uc_abac_state TO `<application-id>`;
   ```

4. Start the app:

   ```bash
   databricks bundle run abac_policy_explorer -t dev --var target_schema=main.uc_abac_state --var warehouse_id=<warehouse-id>
   ```

```{important}
Keep the target schema outside the catalogs your config manages with `--privilege-management-scopes`. Otherwise the next deployment revokes the app's access to the dump tables, since that grant is not in your config.
```

The bundle grants the app `CAN USE` on the warehouse.

## Bundle variables

```{list-table}
:header-rows: 1
:widths: 25 50

* - Variable
  - Description
* - `target_schema`
  - `<catalog>.<schema>` holding the dump tables (required)
* - `warehouse_id`
  - SQL warehouse the app reads the tables through (required)
* - `app_name`
  - Name of the app; defaults to `abac-policy-explorer`
* - `repo_slug`
  - GitHub `<owner>/<repo>` of your config repository, used to link explanations to config files; defaults to `none`, which turns links off
* - `repo_ref`
  - Git ref the links point to; defaults to `main`
* - `config_path_prefix`
  - Path from the repository root to the directory `uc-abac dump` ran in, since dumped config file paths are relative to that directory; defaults to `.` (the repository root)
```

## Example

The [abac_viewer_demo](https://github.com/databricks-solutions/uc-declarative-abac/tree/main/examples/abac_viewer_demo) example deploys a demo catalog, groups, and policies, dumps them, and deploys the app in one script; see {ref}`examples`.
