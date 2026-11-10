(settings)=

# Settings

## Settings file

Place a `uc_abac.yml` file in the working directory (or pass `--settings-file <path>`) to avoid repeating flags on every run:

```{code-block} yaml
:caption: uc_abac.yml

config_dir: ./configs
warehouse_id: <warehouse-id>
use_proxy_information_schema: governance.proxy_information_schema
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

(system-table-proxy-catalogs)=
## Information schema source

Actual-state SQL reads `system.information_schema` by default. Two options change the source. They are mutually exclusive.

### Proxy schema

Set `--use-proxy-information-schema <catalog>.<schema>`, `use_proxy_information_schema` in the settings file, or `UC_ABAC_USE_PROXY_INFORMATION_SCHEMA` to read the views from a curated schema that already exists. The engine never creates or changes that schema. It must be a dedicated schema: `information_schema` is reserved in every catalog, so a proxy cannot be named that.

Both parts must be plain identifiers containing only ASCII letters, digits, and underscores, and may not start with a digit.

### Per-catalog union

A catalog's own `information_schema` only describes objects in that catalog. Set `--use-catalog-information-schema`, `use_catalog_information_schema: true`, or `UC_ABAC_USE_CATALOG_INFORMATION_SCHEMA=true` to read `<catalog>.information_schema.<view>` for each catalog your configs manage, combined with `UNION ALL`. Catalogs that do not exist yet are skipped. You need `USE CATALOG` and the usual `information_schema` visibility on each managed catalog.

### Deprecated: `system_catalog`

`--system-catalog`, `system_catalog`, and `UC_ABAC_SYSTEM_CATALOG` still work but are deprecated and log a warning. Use a proxy schema instead. They cannot be combined with either option above.

### Required views

The proxy schema must expose these views:

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
