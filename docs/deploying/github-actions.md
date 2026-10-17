(github-actions)=

# GitHub Actions

## Deploy action

The repo ships a composite GitHub Action at `deploy/action.yml` so any repository that stores its governance YAML in Git can reconcile Unity Catalog on every push, pull request, or schedule without installing the package or scripting a Python run. Reference it as `databricks-solutions/uc-declarative-abac/deploy@<ref>` (where `<ref>` is a tag, branch, or commit SHA).

Pinning to an immutable ref (for example, a commit SHA or a signed tag) is recommended over `@main`.

### Core inputs

```{list-table}
:header-rows: 1
:widths: 20 10 15 55

* - Input
  - Required
  - Default
  - Description
* - `config-dir`
  - yes
  - None
  - Path to the YAML config directory, relative to the caller's repo root
* - `warehouse-id`
  - yes
  - None
  - SQL warehouse ID used to execute UC queries
* - `system-catalog`
  - no
  - `system`
  - Catalog containing the `information_schema` views used for actual-state queries
```

### Feature scope inputs

```{list-table}
:header-rows: 1
:widths: 25 10 10 55

* - Input
  - Required
  - Default
  - Description
* - `tag-management-scopes`
  - no
  - empty
  - Scope full tag management (add, update, remove) to matching securables; subsumes `tag-assignment-scopes`. Empty (default) disables it; `*` covers all; otherwise comma-separated dotted-prefix patterns.
* - `tag-assignment-scopes`
  - no
  - empty
  - Scope tag assignment (add, update only) to matching securables (same grammar as `tag-management-scopes`). Never removes tags.
* - `privilege-management-scopes`
  - no
  - empty
  - Scope grant and revoke of privileges to matching securables (same grammar as `tag-management-scopes`)
* - `securable-modification-scopes`
  - no
  - empty
  - Scope attribute updates (owner, comment, RFA destinations) on existing catalogs, schemas, tables, volumes, and columns to matching securables. Does not gate function management (always engine-managed).
* - `securable-creation-scopes`
  - no
  - empty
  - Scope creation of missing catalogs, schemas, tables, volumes, and columns to matching securables. Does not gate function creation (always engine-managed).
* - `policy-deletion-scopes`
  - no
  - empty
  - Scope deletion of mask and filter policies absent from config to matching securables. Requires `force: 'true'` in non-interactive CI.
* - `group-creation-scopes`
  - no
  - empty
  - Scope creation of account groups declared under `resources.groups` to those matching by display name. Flat grammar: `*` all, `team_*` prefix, or exact name.
* - `group-modification-scopes`
  - no
  - empty
  - Scope updates of matching account groups (member and assumer reconciliation, renames, expiry) by display name (same flat grammar as `group-creation-scopes`). Updates only, never creates or deletes.
* - `group-deletion-scopes`
  - no
  - empty
  - Scope deletion of Databricks-managed account groups absent from `resources.groups` by display name (same flat grammar). Requires `group-creation-scopes` to be active and `force: 'true'` in non-interactive CI.
* - `governed-tag-deletion-scopes`
  - no
  - empty
  - Scope deletion of governed tags absent from config by name (same flat grammar). System-managed tags are never deleted. Requires `force: 'true'` in non-interactive CI.
* - `domain-creation-scopes`
  - no
  - empty
  - Scope creation of Discovery domains declared under `resources.domains` that are missing, by governed-tag key (same flat grammar).
* - `domain-modification-scopes`
  - no
  - empty
  - Scope metadata updates of existing Discovery domains by governed-tag key (same flat grammar). Updates only, independent of `domain-creation-scopes`.
* - `domain-deletion-scopes`
  - no
  - empty
  - Scope deletion of Discovery domains absent from `resources.domains` by governed-tag key (same flat grammar). Requires `force: 'true'` in non-interactive CI.
```

### Destructive scopes and force

```{list-table}
:header-rows: 1
:widths: 25 10 10 55

* - Input
  - Required
  - Default
  - Description
* - `policy-deletion-scopes`
  - no
  - empty
  - Scope mask and filter policy deletion (see Feature scope inputs above). Requires interactive confirmation unless `force` is 'true'.
* - `group-deletion-scopes`
  - no
  - empty
  - Scope account-group deletion (see Feature scope inputs above). Requires `group-creation-scopes` to be active, interactive confirmation unless `force` is 'true'.
* - `governed-tag-deletion-scopes`
  - no
  - empty
  - Scope governed-tag deletion (see Feature scope inputs above). Requires interactive confirmation unless `force` is 'true'.
* - `domain-deletion-scopes`
  - no
  - empty
  - Scope domain deletion (see Feature scope inputs above). Requires interactive confirmation unless `force` is 'true'.
* - `force`
  - no
  - `false`
  - If 'true', skip every interactive confirmation prompt and auto-confirm destructive actions. Required in non-interactive CI when any destructive gate is set.
```

### Other inputs

```{list-table}
:header-rows: 1
:widths: 25 10 10 55

* - Input
  - Required
  - Default
  - Description
* - `retain-tag-prefixes`
  - no
  - `class.`
  - Comma-separated tag-key prefixes the engine must never remove from securables, even when absent from config (it may still add or update them). Defaults to `class.` to protect UC auto data classification tags. Set to empty string to allow removing any unconfigured tag.
* - `ignore-unresolvable-principals`
  - no
  - empty
  - Comma-separated actual-state principal identifiers whose resolution-failure warning is suppressed (for example, Databricks-managed system service principals). Empty by default.
* - `max-parallel-changes`
  - no
  - `8`
  - Maximum number of worker threads per (securable_type, change_type) execution batch. Set to `1` to disable parallelism and force sequential execution.
* - `timezone`
  - no
  - empty (UTC)
  - IANA timezone used to compute the run date for evaluating `expiry_date` on groups and grant policies (for example `Australia/Melbourne`). Omit to use UTC. An unknown timezone fails the run at config load.
* - `profile`
  - no
  - empty
  - Databricks CLI profile name from `~/.databrickscfg`. Omit to use unified auth via environment variables (for example `DATABRICKS_HOST` and `DATABRICKS_TOKEN` for PAT, or `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` for OAuth M2M). Set these on the step's `env` block.
* - `dry-run`
  - no
  - `false`
  - If 'true', print the planned changes without executing them.
```

### Deprecated inputs

The following inputs are deprecated and slated for removal. Use {ref}`deprecations` for migration guidance.

```{list-table}
:header-rows: 1
:widths: 25 10 10 55

* - Input
  - Reason
  - Migration
  - Notes
* - `use-workspace-scim`
  - Deprecated
  - Omit it; the account path now lists all account principals
  - The engine logs a deprecation warning when set. Incompatible with group management.
* - `skip-users-fetch`
  - Deprecated
  - Omit it
  - The engine logs a deprecation warning when set. Not intended for production use.
* - `taggable-management-scopes`, `securable-management-scopes`
  - Renamed
  - Use `securable-modification-scopes`
  - The engine logs a deprecation warning.
* - `taggable-creation-scopes`
  - Renamed
  - Use `securable-creation-scopes`
  - The engine logs a deprecation warning.
* - `group-management-scopes`
  - Renamed
  - Use `group-modification-scopes`
  - The engine logs a deprecation warning.
* - `domain-management-scopes`
  - Renamed
  - Use `domain-modification-scopes`
  - The engine logs a deprecation warning.
```

### Example workflow

```{code-block} yaml
:caption: .github/workflows/deploy-uc-abac-governance.yml

name: Deploy UC ABAC governance
on:
  pull_request:
    paths: ['configs/**']
  push:
    branches: [main]
    paths: ['configs/**']
  schedule:
    # It is recommended to schedule daily, preferably once in the morning and once in the evening
    - cron: '0 22 * * *'  # ~8 to 9am Sydney time: revoke any privileges whose expiry_date has just passed
    - cron: '0 7 * * *'   # ~5 to 6pm Sydney time: re-sync to catch any drift introduced during the day

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: databricks-solutions/uc-declarative-abac/deploy@<tag>
        with:
          config-dir: configs/
          warehouse-id: ${{ vars.DATABRICKS_WAREHOUSE_ID }}
          tag-management-scopes: '*'
          privilege-management-scopes: '*'
          dry-run: ${{ github.event_name == 'pull_request' }}
          force: 'true'
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
```

Swap `DATABRICKS_TOKEN` for `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET` for OAuth M2M, or the Azure SP variables for Azure Databricks workspaces.

## Offline validation action

The repo ships a lightweight companion action at `validate/action.yml` that runs `uc-abac validate` to parse, resolve, and validate the YAML without contacting Databricks (no warehouse ID, credentials, or secrets required). It is ideal as a feature-branch CI step before a pull request is raised. Reference it as `databricks-solutions/uc-declarative-abac/validate@<ref>`.

### Validation inputs

```{list-table}
:header-rows: 1
:widths: 25 10 15 55

* - Input
  - Required
  - Default
  - Description
* - `config-dir`
  - yes
  - None
  - Path to the YAML config directory, relative to the caller's repo root
* - `ref-override-strategy`
  - no
  - `merge`
  - Deprecated: omit it. How sibling fields on a `$ref` entry combine with the referenced definition.
```

### Validation example workflow

```{code-block} yaml
:caption: .github/workflows/validate-uc-abac-configs.yml

name: Validate UC ABAC configs

on:
  push:

jobs:
  validate:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: databricks-solutions/uc-declarative-abac/validate@<tag>
        with:
          config-dir: configs/
```

## Dump action

A third companion action at `dump/action.yml` runs `uc-abac dump` to snapshot your deployed governance into tables for reporting and audits (see {ref}`dumping-state`). Reference it as `databricks-solutions/uc-declarative-abac/dump@<ref>`.

### Dump inputs

```{list-table}
:header-rows: 1
:widths: 25 10 15 55

* - Input
  - Required
  - Default
  - Description
* - `config-dir`
  - yes
  - None
  - Path to the YAML config directory, relative to the caller's repo root
* - `warehouse-id`
  - yes
  - None
  - SQL warehouse ID used to read state and write the tables
* - `target-schema`
  - yes
  - None
  - Schema to write the snapshot tables into, as `<catalog>.<schema>`. Created when it does not exist.
* - `system-catalog`
  - no
  - `system`
  - Catalog containing the `information_schema` views used for state queries
* - `timezone`
  - no
  - empty (UTC)
  - IANA timezone for the run date that decides which grant policies have expired. Omit to use UTC.
* - `profile`
  - no
  - empty
  - Databricks CLI profile; omit to use unified auth via the step's `env`.
* - `dry-run`
  - no
  - `false`
  - If 'true', log the statements that would run without executing them
* - `replace-tables`
  - no
  - `false`
  - If 'true', recreate each table before loading it, so its columns are in spec order instead of appending new columns at the end
* - `max-parallel-changes`
  - no
  - `8`
  - Maximum number of SQL statements run concurrently while writing tables
```

### Dump example workflow

```{code-block} yaml
:caption: .github/workflows/dump-uc-abac-state.yml

name: Dump UC ABAC state

on:
  schedule:
    - cron: '0 20 * * *'
  workflow_dispatch:

jobs:
  dump:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: databricks-solutions/uc-declarative-abac/dump@<tag>
        with:
          config-dir: configs/
          warehouse-id: ${{ vars.DATABRICKS_WAREHOUSE_ID }}
          target-schema: main.uc_abac_state
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
```

The dump action's permission requirements are covered on {ref}`dumping-state`.
