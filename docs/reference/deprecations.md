(deprecations)=

# Deprecations

Deprecated items still work but log a deprecation warning unless noted otherwise. Each deprecated flag's settings-file key (the flag name in snake_case, for example `enable_tag_management`) and `UC_ABAC_*` environment variable are deprecated along with it; see {ref}`settings`.

```{list-table}
:header-rows: 1
:widths: 35 35 30

* - Deprecated
  - Replacement
  - Notes
* - `python -m uc_abac`
  - Use console script `uc-abac` or `uc-declarative-abac`
  - The module invocation still works but is not recommended. Use the console scripts instead.
* - Legacy flat invocation: `uc-abac --config-dir ... --warehouse-id ... [--dry-run]`
  - Use `uc-abac deploy --config-dir ... --warehouse-id ... [--dry-run]`
  - The old form (without `deploy`) still works but logs a deprecation warning. Use the modern `deploy` subcommand syntax.
* - `--use-workspace-scim`
  - Omit; use account path (default)
  - Slated for removal. The account identity API path now provides access to all account principals; workspace SCIM mode is no longer needed. Incompatible with `resources.groups`.
* - `--skip-users-fetch`
  - Omit
  - Slated for removal. Skips listing users and treats the user set as empty. Not intended for production use.
* - `--enable-tag-management`
  - Use `--tag-management-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--enable-privilege-management`
  - Use `--privilege-management-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--enable-taggable-management`
  - Use `--securable-modification-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--enable-taggable-creation`
  - Use `--securable-creation-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--manage-tags-for-namespaces`
  - Use `--tag-management-scopes`
  - Superseded by the unified scope flag. Only effective with `--enable-tag-management` (also deprecated).
* - `--manage-privileges-for-namespaces`
  - Use `--privilege-management-scopes`
  - Superseded by the unified scope flag. Only effective with `--enable-privilege-management` (also deprecated).
* - `--manage-taggables-for-namespaces`
  - Use `--securable-modification-scopes`
  - Superseded by the unified scope flag. Only effective with `--enable-taggable-management` (also deprecated).
* - `--create-taggables-for-namespaces`
  - Use `--securable-creation-scopes`
  - Superseded by the unified scope flag. Only effective with `--enable-taggable-creation` (also deprecated).
* - `--delete-policies-for-namespaces`
  - Use `--policy-deletion-scopes`
  - Superseded by the unified scope flag. Only effective with `--enable-policy-deletion` (also deprecated).
* - `--taggable-management-scopes`
  - Use `--securable-modification-scopes`
  - Renamed for clarity; scope now covers all securables (catalogs, schemas, tables, volumes, columns).
* - `--securable-management-scopes`
  - Use `--securable-modification-scopes`
  - Intermediate alias, now replaced by the final name.
* - `--taggable-creation-scopes`
  - Use `--securable-creation-scopes`
  - Renamed for clarity; scope now covers all securables (catalogs, schemas, tables, volumes, columns).
* - `--group-management-scopes`
  - Use `--group-modification-scopes`
  - Renamed to clarify that the flag scopes updates only, not creation or deletion.
* - `--domain-management-scopes`
  - Use `--domain-modification-scopes`
  - Renamed to clarify that the flag scopes updates only, not creation or deletion.
* - `--enable-group-creation`
  - Use `--group-creation-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--enable-group-management`
  - Use `--group-modification-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--enable-group-deletion`
  - Use `--group-deletion-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--enable-governed-tag-deletion`
  - Use `--governed-tag-deletion-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--enable-policy-deletion`
  - Use `--policy-deletion-scopes`
  - The old enable/disable boolean gate is superseded by scoped feature flags.
* - `--ref-override-strategy replace`
  - Omit; use default `merge`
  - Slated for removal. The shallow-replacement behaviour is the legacy form; recursive deep-merge is now the default and recommended approach. Setting `replace` logs a deprecation warning.
* - Governed tag `comment` field
  - Use `description`
  - The `comment` field on governed tags is a backward-compatible alias for `description` on input. Use `description` going forward.
* - Template variable delimiter `{{ name }}`
  - Use `${name}` (tight, no inner whitespace)
  - The legacy curly-brace form is still supported and functional without a warning. The recommended form is `${name}`.
```
