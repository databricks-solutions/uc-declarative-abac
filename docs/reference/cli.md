(cli)=

# CLI reference

The CLI has three subcommands. Global flags precede the subcommand name; subcommand-specific flags follow it.

## Subcommands

(validate-subcommand)=

### validate

Parse, resolve, and validate YAML configs locally. Requires `--config-dir`; no warehouse ID or Databricks credentials needed.

Usage:
```bash
uc-abac validate --config-dir ./configs
```

(deploy-subcommand)=

### deploy

Apply governance changes to Unity Catalog. Requires `--config-dir` and `--warehouse-id`. Add `--dry-run` to preview changes without executing.

Usage:
```bash
uc-abac deploy --config-dir ./configs --warehouse-id <id> --dry-run
```

(dump-subcommand)=

### dump

Write the current Unity Catalog governance state behind a config to snapshot tables in a target schema, enabling reporting and auditing of deployed governance without running a deploy. Requires `--config-dir`, `--warehouse-id`, and `--target-schema`.

Usage:
```bash
uc-abac dump --config-dir ./configs --warehouse-id <id> --target-schema main.uc_abac_state
```

## Global flags

Precede the subcommand name.

`--version`
: Show the tool version and exit.

`--verbose`
: Print full tracebacks on failure.

`--quiet`
: Suppress non-error log output.

`--settings-file <path>`
: Path to a YAML settings file (default: `./uc_abac.yml` if present). See {ref}`settings`.

## deploy flags

### Connection and core

```{list-table}
:header-rows: 1
:widths: 25 10 20 45

* - Flag
  - Required
  - Default
  - Description
* - `--config-dir`
  - yes
  - None
  - Path to the YAML config directory
* - `--warehouse-id`
  - yes
  - None
  - SQL warehouse ID for executing Unity Catalog queries
* - `--profile`
  - no
  - None
  - Databricks CLI profile name from `~/.databrickscfg`. Omit to use unified auth via environment variables or metadata service
* - `--system-catalog`
  - no
  - `system`
  - Catalog containing `information_schema` views used for state queries. Set to a custom proxy catalog to use a curated view layer
* - `--timezone`
  - no
  - UTC
  - IANA timezone (e.g. `Australia/Melbourne`) used to compute the run date for evaluating `expiry_date` on groups and grant policies. Unknown timezones fail at load time
* - `--dry-run`
  - no
  - `false`
  - Print planned changes without executing them
* - `--settings-file`
  - no
  - None
  - Path to a YAML settings file; see {ref}`settings`
```

### Feature scopes

Feature scopes gate deployment of each feature type. Each flag accepts comma-separated patterns; empty (default) disables the feature. See {ref}`feature-scopes` for the full scope grammar and examples.

`--tag-management-scopes`
: Scope full tag management (add, update, remove assignments) to matching securables. Subsumes `--tag-assignment-scopes`.

`--tag-assignment-scopes`
: Scope tag assignment (add missing tags, update values) without removing tags.

`--privilege-management-scopes`
: Scope GRANT/REVOKE privilege management.

`--securable-modification-scopes`
: Scope attribute updates (owner, comment, rfa_destinations) on existing catalogs, schemas, tables, volumes, and columns. Functions are always managed by the engine.

`--securable-creation-scopes`
: Scope creation of missing catalogs, schemas, tables, volumes, and columns. Functions are always created by the engine.

`--policy-deletion-scopes`
: Scope deletion of mask and filter policies absent from config. Requires interactive confirmation unless `--force` is set.

`--group-creation-scopes`
: Scope creation of account groups declared under `resources.groups`. Groups are created empty; use `--group-modification-scopes` to populate membership.

`--group-modification-scopes`
: Scope reconciliation of members and assumers of existing account groups and groups created the same run.

`--group-deletion-scopes`
: Scope deletion of Databricks-managed account groups absent from config. External (IdP-provisioned) and system groups are never deleted. Requires `--group-creation-scopes` to be active and at least one group under `resources.groups`. Requires interactive confirmation unless `--force` is set.

`--governed-tag-deletion-scopes`
: Scope deletion of governed tags absent from config. System-managed tags are never deleted. Requires interactive confirmation unless `--force` is set.

`--domain-creation-scopes`
: Scope creation of Discovery domains declared under `resources.domains` that are missing from the workspace.

`--domain-modification-scopes`
: Scope metadata updates of Discovery domains declared under `resources.domains` that already exist.

`--domain-deletion-scopes`
: Scope deletion of Discovery domains absent from `resources.domains`. Requires interactive confirmation unless `--force` is set.

### Safety and behaviour

```{list-table}
:header-rows: 1
:widths: 25 10 20 45

* - Flag
  - Required
  - Default
  - Description
* - `--force`
  - no
  - `false`
  - Skip every interactive confirmation prompt and auto-confirm destructive actions. Required in non-interactive (CI) contexts when any destructive gate is active; the run errors if you omit it
* - `--retain-tag-prefixes`
  - no
  - `class.`
  - Comma-separated tag-key prefixes that must never be removed, even when absent from config (the engine may still add or update them). Protects UC auto data classification tags by default. Pass an empty string to allow removing any unconfigured tag
* - `--ignore-unresolvable-principals`
  - no
  - (empty)
  - Comma-separated principal identifiers (usernames for users, application_ids for service principals, display names for groups) whose resolution-failure warnings are suppressed. Primarily for Databricks-managed system service principals that appear in system tables but can't be resolved
* - `--max-parallel-changes`
  - no
  - 8
  - Maximum number of changes applied concurrently. Set to `1` to apply changes one at a time
```

### Deprecated flags

Older flags such as `--use-workspace-scim`, the `--enable-*` gates, and the
`--*-management-scopes` aliases still work but log a warning. See {ref}`deprecations` for the
full list and their replacements.

## validate flags

`validate` requires only `--config-dir`. It accepts the same flags as `deploy` apart from
`--warehouse-id` and `--dry-run`, so one settings file serves both commands. Of those, only the
ones that affect how configs are loaded have any effect: `--timezone` (the run date used for
`expiry_date`) and the deprecated `--ref-override-strategy`. `validate` never contacts
Databricks.

## dump flags

```{list-table}
:header-rows: 1
:widths: 25 10 20 45

* - Flag
  - Required
  - Default
  - Description
* - `--config-dir`
  - yes
  - None
  - Path to the YAML config directory
* - `--warehouse-id`
  - yes
  - None
  - SQL warehouse ID for reading state and writing tables
* - `--target-schema`
  - yes
  - None
  - Schema to write snapshot tables into, as `<catalog>.<schema>`. Created when it doesn't exist
* - `--profile`
  - no
  - None
  - Databricks CLI profile name from `~/.databrickscfg`. Omit to use unified auth
* - `--system-catalog`
  - no
  - `system`
  - Catalog containing `information_schema` views for state queries
* - `--timezone`
  - no
  - UTC
  - IANA timezone used to compute the run date for evaluating `expiry_date` on grant policies
* - `--dry-run`
  - no
  - `false`
  - Log the SQL statements that would run without executing them
* - `--replace-tables`
  - no
  - `false`
  - Recreate each table (with `CREATE OR REPLACE`) before loading, placing new columns in spec order. By default, rows are swapped atomically into existing tables
* - `--max-parallel-changes`
  - no
  - 8
  - Maximum SQL statements run concurrently while writing tables. Set to 1 for sequential writes
* - `--settings-file`
  - no
  - None
  - Path to a YAML settings file
```

## Settings resolution

Every flag can also be set in a `uc_abac.yml` settings file (field names use underscores, e.g. `warehouse_id`, `tag_management_scopes`) or via `UC_ABAC_*` environment variables (e.g. `UC_ABAC_WAREHOUSE_ID`, `UC_ABAC_TAG_MANAGEMENT_SCOPES`). Precedence is: defaults < settings file < environment variables < CLI flags. See {ref}`settings` for full details.

## Exit codes

```{list-table}
:header-rows: 1
:widths: 15 60

* - Exit code
  - Meaning
* - `0`
  - Success
* - `1`
  - Execution errors: one or more changes failed to apply
* - `2`
  - Usage error, such as unrecognised arguments or an invalid flag combination
* - `3`
  - Config or validation error, such as invalid YAML, an unknown key, or an unresolvable reference
* - `4`
  - Databricks or authentication error
* - `130`
  - Interrupted, for example with Ctrl+C
```
