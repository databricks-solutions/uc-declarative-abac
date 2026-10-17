(settings)=

# Settings

## Settings file

Place a `uc_abac.yml` file in the working directory (or pass `--settings-file <path>`) to avoid repeating flags on every run:

```{code-block} yaml
:caption: uc_abac.yml

config_dir: ./configs
warehouse_id: <warehouse-id>
system_catalog: system_catalog_proxy
tag_management_scopes: '*'
privilege_management_scopes: '*'
timezone: Australia/Melbourne
max_parallel_changes: 16
```

Settings keys use snake_case (for example, `warehouse_id`, not `warehouse-id`).

## Environment variables

Any setting can be set via `UC_ABAC_*` environment variables (for example, `UC_ABAC_WAREHOUSE_ID`, `UC_ABAC_SYSTEM_CATALOG`, `UC_ABAC_TAG_MANAGEMENT_SCOPES='*'`).

### Precedence

Settings are resolved in this order (first match wins):

1. CLI flags (highest priority)
2. Environment variables (`UC_ABAC_*`)
3. Settings file (`uc_abac.yml`)
4. Built-in defaults (lowest priority)

## Timezone setting

The `timezone` setting (or `UC_ABAC_TIMEZONE` environment variable) specifies an IANA timezone used to compute the run date when evaluating `expiry_date` on groups and grant policies. The default is UTC. An unknown timezone fails the run at config load.

Example:

```bash
uc-abac deploy --config-dir ./configs --warehouse-id <id> --timezone Australia/Melbourne
```

## System-table proxy catalogs

Actual-state SQL reads `system.information_schema` by default. Set `--system-catalog <catalog>`, `system_catalog` in the settings file, or `UC_ABAC_SYSTEM_CATALOG` to use a curated proxy catalog instead.

### Identifier rules

The catalog value must be a plain identifier containing only ASCII letters, digits, and underscores, and may not start with a digit.

### Required views

The proxy must expose these views under its `information_schema` schema:

```{list-table}
:header-rows: 1
:widths: 20 50

* - Domain
  - Required views
* - tags
  - `catalog_tags`, `schema_tags`, `table_tags`, `volume_tags`, `column_tags`
* - privileges
  - `catalog_privileges`, `schema_privileges`, `table_privileges`, `volume_privileges`
* - securables
  - `catalogs`, `schemata`, `tables`, `columns`, `volumes`, `routines`, `parameters`
* - policies
  - `abac_policy_definitions`
```

### Column retention

The views must retain every column projected or filtered by the corresponding Databricks information-schema view. In particular, this includes:

- Object names and tag columns
- `privilege_type`, `grantee`, and `inherited_from` for privileges
- `table_type`, `comment`, owner columns (`*_owner`), `routine_definition`, and `ordinal_position` for securables
- Policy type and securable-name columns in `abac_policy_definitions`

```{warning}
**Visibility warning:** A workspace-scoped proxy must expose every configured object. If it hides rows, existing objects can appear absent and the engine can plan incorrect creates, tag removals, or privilege revokes.
```
