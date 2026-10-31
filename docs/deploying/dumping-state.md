(dumping-state)=

# Dumping current state

The `uc-abac dump` command reads the current Unity Catalog governance state behind a config and writes it as queryable tables into a target schema, so you can report on or audit what is deployed without running a deploy. The {ref}`policy-explorer` app visualises these tables.

## Command

```bash
uc-abac dump --config-dir ./configs --warehouse-id <warehouse-id> --target-schema main.uc_abac_state
```

## Flags

- `--config-dir`: Path to the YAML config directory (required)
- `--warehouse-id`: SQL warehouse ID (required)
- `--target-schema <catalog>.<schema>`: Schema to write the tables into; created, with a comment describing it, when it does not exist (required). Also settable as `target_schema` in `uc_abac.yml` or `UC_ABAC_TARGET_SCHEMA`
- `--profile`: Optional Databricks CLI profile name from `~/.databrickscfg`; omit to use unified auth via env vars
- `--system-catalog`: Catalog containing the `information_schema` views; defaults to `system`
- `--timezone`: IANA timezone for the run date used to evaluate grant-policy expiry; defaults to UTC
- `--max-parallel-changes`: Maximum number of SQL statements run concurrently while writing tables; defaults to 8
- `--replace-tables`: Recreate each table before loading (brief empty window); default is false (swap rows atomically)
- `--dry-run`: Log what would be written without executing

## Atomic semantics

Rows are loaded into a `_tmp_<table>` staging table first and then swapped into the table in one atomic step, so readers never see an empty or partly loaded table. A table that fails to load keeps its previous contents, and the run exits non-zero. Pass `--replace-tables` to always recreate each table, so its columns are in spec order; a recreated table is briefly empty while it reloads, and is left empty if that reload fails.

## Column handling

When a new version adds columns to an existing table, they are appended at the end. Column comments are kept up to date either way. A table that does not yet exist is created. An existing table that cannot be updated in place (for example, after an incompatible column type change) is recreated instead, with a warning.

## Dumped tables

```{list-table}
:header-rows: 1
:widths: 25 25 50

* - Table
  - Contents
  - Based on
* - `securables`
  - One row per catalog, schema, table, volume, and function in the config, with owner, comment, table columns, and function definition and parameters
  - `information_schema` catalogs / schemata / tables / volumes / routines
* - `function_rules`
  - One row per {ref}`RLS mapping rule or filter condition rule <functions-rls-mapping-rules>` of each function in `securables`, with its grouping (`AND` for `match_rules`, `OR` for `match_any_of_rules`). Joins to `securables` on `catalog_name`, `schema_name`, `function_name` = `securable_name`, and `securable_type` = `'FUNCTION'`
  - The config
* - `securable_tags`
  - Tags assigned to securables (including columns) in the config's catalogs
  - `information_schema.*_tags`
* - `securable_privileges`
  - Privileges granted on securables in the config's catalogs
  - `information_schema.*_privileges`
* - `abac_policies`
  - Row filter and column mask policies in the config's catalogs
  - `information_schema.abac_policy_definitions`
* - `pseudo_policies`
  - The config's active grant policies, in the same columns as `abac_policies` (read from the config, since grant policies are expanded into concrete privileges)
  - uc-abac config
* - `governed_tags`
  - The account's governed tags and their allowed values
  - Tag Policies API
* - `governed_tag_assigners`
  - Principals permitted to assign every governed tag the config references
  - Tag policy access-control rule sets
* - `domains`
  - The workspace's Discovery domains
  - Domains API
* - `principals`
  - The account's users, groups, and service principals
  - `system.access.principals_latest`
* - `group_members`
  - Direct members of every group the config references (except `account users`)
  - `system.access.parent_groups_latest`
* - `group_assumers`
  - Principals permitted to assume every group the config references (except `account users`)
  - Group access-control rule sets
```

## Principals

Principals are written by their canonical identifier (username for users, group name for groups, or service principal application ID for service principals), matching the system tables, so the tables join directly to them.

## Config file path

Every table's first column, `config_file_path`, is the config YAML file that declares the row's object (for a privilege, the active grant policy that produces it), or NULL when the object is not in the config.

## Required permissions

The identity used to run the dump action needs:

- The {ref}`authentication` permissions required for read access to state (`workspace admin` and `metastore admin`)
- `USE CATALOG` and `CREATE SCHEMA` on the target catalog when the schema does not yet exist, or `USE SCHEMA` and `CREATE TABLE` (and `MODIFY` on the tables after the first run) when it does

For full context, see {ref}`github-actions`.
