(deployment-semantics)=

# Deployment semantics

## Deployment

The engine is designed to run in CI/CD. Use the GitHub Action on a repository that holds your YAML files: on push or on a schedule, the action runs the engine against your configs and declaratively deploys ABAC governance to your Databricks workspace and Unity Catalog.

It is recommended to run the deployment whenever a new version of your YAML files is released, as well as running a scheduled deployment at least once per day to reduce drift and to ensure features like the grant policy `expiry_date` work as intended.

## Deployment semantics

Not all object types are managed the same way:

```{list-table}
:header-rows: 1
:widths: 25 25 50

* - Category
  - Behaviour
  - Examples
* - Group members and assumers
  - Additive and removals, gated by scopes
  - With `--group-modification-scopes`, each of a group's `members` and `assumers` is reconciled only if supplied in config (omitted means left untouched, not fetched; empty list means remove all). For existing groups and groups created the same run. Missing groups are created empty only with `--group-creation-scopes`. With neither scope, configured groups are ignored.
* - Governed tags
  - Additive and deletes, gated by scopes
  - Unconfigured governed tags are deleted from the account only if they fall in `--governed-tag-deletion-scopes`.
* - Discovery domains
  - Additive and deletes, gated by scopes
  - Explicit `resources.domains` entries are created within `--domain-creation-scopes` and updated within `--domain-modification-scopes` (independent gates). Domains absent from config are deleted only within `--domain-deletion-scopes`.
* - UC objects and attributes
  - Additive only (create and update, never deletes)
  - Catalogs, schemas, tables, volumes, functions, comments
* - Tags and grant policies
  - Additive and removals/revokes, gated by scopes
  - Tag assignments on objects, grant statements. Tag removals only under `--tag-management-scopes`; `--tag-assignment-scopes` is additive only.
* - Mask and filter policies
  - Additive by default; deletes when authoritative, gated by scopes
  - Column masking policies, row filter policies
```

### Securable creation note

By default, the engine assumes that securables (catalogs, schemas, tables, volumes) already exist in Unity Catalog and will only manage tags, grants, and policies on them. If you want the engine to create securables that do not yet exist, add their namespaces to `--securable-creation-scopes`.

### Mask and filter policy deletion

Mask and filter policies are additive by default (create and update, never delete). With `--policy-deletion-scopes`, config becomes authoritative over mask and filter policies on in-scope securables: any actual mask or filter policy discovered on an in-scope securable but not declared in config is deleted, regardless of whether that securable declares a `policies` list. Like governed-tag deletion, it requires an interactive `yes` confirmation at the terminal unless `--force` is set. Grant policies are unaffected; their privileges are granted and revoked under `--privilege-management-scopes`.

```{warning}
**Important: tag and grant drift.** For catalogs governed by this project, the engine treats the YAML configs as the sole source of truth for tags and privilege grants. If a tag or grant is manually added to an object in a governed catalog (for example, via the Databricks UI or a direct SQL statement), the engine will remove it on the next run to re-sync with the declared config. All tag assignments and privilege grants for governed catalogs must be managed through these YAML files.
```
