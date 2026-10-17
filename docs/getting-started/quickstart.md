(quickstart)=

# Quick start

## Validate configs locally

No warehouse or credentials required:

```bash
uc-abac validate --config-dir examples/finance_demo/configs
```

## Deploy with env-based authentication

Set your Databricks credentials and warehouse ID, then do a dry run to preview changes:

```bash
export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
export DATABRICKS_TOKEN=<personal-access-token>
uc-abac deploy --config-dir examples/finance_demo/configs \
  --warehouse-id <warehouse-id> \
  --tag-management-scopes '*' \
  --privilege-management-scopes '*' \
  --dry-run
```

If the plan looks correct, apply it:

```bash
uc-abac deploy --config-dir examples/finance_demo/configs \
  --warehouse-id <warehouse-id> \
  --tag-management-scopes '*' \
  --privilege-management-scopes '*'
```

## Deploy with a local profile

If you have a Databricks CLI profile configured in `~/.databrickscfg`, you can use it instead of setting env vars:

```bash
uc-abac deploy --config-dir examples/finance_demo/configs \
  --warehouse-id <warehouse-id> \
  --profile <profile-name> \
  --tag-management-scopes '*' \
  --privilege-management-scopes '*' \
  --dry-run
```

## About feature scopes

By default, every mutating feature is disabled. The quick start example passes `--tag-management-scopes '*'` and `--privilege-management-scopes '*'` to enable tag and privilege management across all configured resources. Other features like group creation and policy deletion are off by default and must be explicitly enabled by passing their scopes.

Read {ref}`feature-scopes` for the full scope grammar, and see which other features you might need.

## Next steps

- {ref}`authentication` for credential setup options (OAuth, Azure service principals, metadata service)
- {ref}`github-actions` to deploy from CI/CD on every push or schedule
- {ref}`cli` for all available commands and flags
- {ref}`examples` for a breakdown of the finance_demo and how to adapt it
