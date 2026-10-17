(feature-scopes)=

# Feature scopes

Every mutating feature is gated by a single `--<feature>-scopes` flag that controls which resources the feature applies to.

## Scope grammar

An empty scope (the default) disables the feature entirely. `*` covers everything. Otherwise, the value is a comma-separated list of patterns.

The grammar differs for securable scopes (catalogs, schemas, tables, volumes, columns) and flat scopes (groups by display name, governed tags by name, Discovery domains by governed-tag key).

## Securable scopes

Securable-scope patterns match a dotted `full_name` with downward inheritance:

```{list-table}
:header-rows: 1
:widths: 20 50

* - Pattern
  - Matches
* - `main`
  - The `main` catalog and its whole subtree (including `main.sales`, `main.sales.orders`, etc.), but not `maintenance` or other catalogs
* - `main.*`
  - Everything under `main` excluding the catalog node itself
* - `main.sales`
  - The `main.sales` schema and its entire subtree
* - `main.sales.*`
  - All tables and below of that schema, excluding the schema node
* - `main.salesforce*`
  - Schemas whose name starts with `salesforce` (for example `main.salesforce_bronze`, `main.salesforce_silver`) and their subtrees
* - `*`
  - Everything
```

**Pattern rules:**

- A trailing `*` is a raw name prefix match
- An entry without `*` covers the exact node and everything beneath it
- Wildcards are only valid as the final character: leading or middle `*` such as `*.pii` or `main.*.orders` is rejected
- Functions are always engine-managed and flow through regardless of scope

## Flat scopes

Groups, governed tags, and Discovery domains use flat scopes (no hierarchy):

- An entry with no `*` matches that one name exactly
- A trailing `*` is a name prefix match (for example `team_*`)
- `*` matches all

## Feature scope flags

```{list-table}
:header-rows: 1
:widths: 35 50

* - Flag
  - Governs
* - `--tag-management-scopes`
  - Create, update, and remove tag assignments on securables (subsumes `--tag-assignment-scopes`)
* - `--tag-assignment-scopes`
  - Create and update tag assignments on securables, never removing tags
* - `--privilege-management-scopes`
  - Grant and revoke privileges
* - `--securable-modification-scopes`
  - Attribute updates (owner, comment, RFA destinations) on existing catalogs, schemas, tables, volumes, and columns (not functions, which are always engine-managed)
* - `--securable-creation-scopes`
  - Create catalogs, schemas, tables, volumes, and columns declared in config but absent from UC (not functions, which are always engine-managed)
* - `--policy-deletion-scopes`
  - Delete mask and filter policies absent from config
* - `--group-creation-scopes`
  - Create account groups declared under `resources.groups`
* - `--group-modification-scopes`
  - Reconcile membership and assumers of existing account groups
* - `--group-deletion-scopes`
  - Delete Databricks-managed account groups absent from config
* - `--governed-tag-deletion-scopes`
  - Delete governed tags absent from config
* - `--domain-creation-scopes`
  - Create Discovery domains declared under `resources.domains` that are missing
* - `--domain-modification-scopes`
  - Update metadata of existing Discovery domains declared under `resources.domains`
* - `--domain-deletion-scopes`
  - Delete Discovery domains absent from `resources.domains`
```

(feature-scopes-tags)=

## Tag scopes and grant matching

`--tag-management-scopes` adds, updates, and removes tags; `--tag-assignment-scopes` only adds
and updates them, so tags applied outside config are kept. A securable matched by both is fully
managed. Grant policies always match against tags: for securables whose tags the engine manages
this run, they match the tags declared in config; elsewhere they match the tags currently
deployed in Unity Catalog. Tags with a prefix in `--retain-tag-prefixes` (default `class.`) are
never removed; see {ref}`cli`.

## Important constraints

```{important}
**The universe is bounded by the catalogs in your config.** These scopes only ever narrow the set of configured catalogs. The engine only fetches and reconciles state for catalogs declared under `resources.catalogs`. So `*` means "all configured catalogs" (not every catalog in the metastore), and a scope naming a catalog absent from config matches nothing and logs a zero-match warning.

To bring a new catalog under management, add it to your config.
```

## Destructive scopes

Destructive scopes require interactive confirmation at the terminal unless you set `--force`:

- `--policy-deletion-scopes`
- `--group-deletion-scopes`
- `--governed-tag-deletion-scopes`
- `--domain-deletion-scopes`

In non-interactive CI contexts (GitHub Actions, scripted runs), you must set `--force` or the run aborts with an error asking you to set this flag.

## Zero-match warnings

A scope entry that matches no configured resource logs a warning (indicating a likely typo) but never fails the run.

## Examples

```bash
# Manage privileges on schemas and below of main, but leave catalog-level grants alone
uc-abac deploy --config-dir ./configs --warehouse-id <id> \
  --privilege-management-scopes 'main.*'

# Manage tags across two catalogs; create only the salesforce_* schemas of main
uc-abac deploy --config-dir ./configs --warehouse-id <id> \
  --tag-management-scopes 'main,other' \
  --securable-creation-scopes 'main.salesforce*'
```

## Domain-specific behaviour

For domain-specific feature behavior and interplay with other scopes, see:

- {ref}`groups`
- {ref}`governed-tags`
- {ref}`domains`
- {ref}`tables` (for securable-creation scopes and column handling)
