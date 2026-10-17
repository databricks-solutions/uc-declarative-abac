(principals)=

# Principals

## Principal naming conventions

When specifying principals for `owner`, `to`, `except`, or grant targets, use the appropriate identifier for the type of principal:

```{list-table}
:header-rows: 1
:widths: 25 30 45

* - Principal type
  - Identifier to use
  - Example
* - User
  - Email or username
  - `jane.doe@company.com`
* - Group
  - Display name
  - `data_engineers`
* - Service principal
  - Display name
  - `sp_data_governor`
```

```{important}
Service principal display names must be unique within the account. If two service principals share the same display name, the engine cannot resolve the intended principal and the deployment will fail.
```

## Unresolvable principals

The engine handles principals differently depending on where they come from:

**Config-side principal**: A principal in your config that can't be resolved (for example, a mistyped group name) is a fatal error and fails the run immediately.

**Actual-state principal**: A principal that exists only in UC's deployed state and can't be resolved to an account principal is dropped from the diff and reported as a non-fatal warning. The run still succeeds. This covers Databricks-managed system service principals (used internally by features like predictive optimization and scheduled dashboard refresh), which show up in the system tables as application ID UUIDs, aren't listed as account principals, and cannot be managed.

### Suppressing warnings for known unresolvable principals

You can suppress resolution-failure warnings for specific actual-state principals using the `--ignore-unresolvable-principals` flag. Supply a comma-separated list of principal identifiers:

- For users: usernames
- For service principals: `application_id` UUIDs
- For groups: display names

This is primarily useful for Databricks-managed system service principals that appear in system tables but can't be resolved. Without this flag, you would see a warning on every deployment run. See {ref}`cli` for details.
