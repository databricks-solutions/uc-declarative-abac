# UC Declarative ABAC

[![Documentation](https://readthedocs.org/projects/uc-declarative-abac/badge/?version=latest)](https://uc-declarative-abac.readthedocs.io/en/latest/)
[![CI](https://github.com/liamperritt/uc-declarative-abac/actions/workflows/ci.yml/badge.svg)](https://github.com/liamperritt/uc-declarative-abac/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/liamperritt/uc-declarative-abac)](LICENSE)

**Declare governance in YAML. Version it. Deploy it.**

UC Declarative ABAC lets you define your Databricks Unity Catalog Attribute-Based Access Control
(ABAC) governance model in declarative YAML files. The engine reads your configs, queries Unity
Catalog for the current state, computes the difference, and applies only the changes needed.
Run it from the `uc-abac` CLI or as a GitHub Action from the repository that holds your YAML.

**Documentation: [uc-declarative-abac.readthedocs.io](https://uc-declarative-abac.readthedocs.io/)**

## What it manages

- **Tag-based ABAC policies**: column masks, row filters, and grants that match tagged objects.
- **Unity Catalog objects**: catalogs, schemas, tables, volumes, and functions, with owners,
  comments, tags, and request-for-access destinations.
- **Governed tags** with allowed values and assigners, and **Discovery domains**.
- **Account groups**, their members, and assumers.
- **Reusable definitions** with `$ref` overrides and template variables, so one definition can
  deploy to dev, test, and prod.

Every mutating feature is off until you give it a scope, so you choose exactly what the engine
may change.

## Quick start

```bash
uv venv && uv sync --extra dev

# Validate configs offline (no workspace or credentials needed)
uc-abac validate --config-dir examples/finance_demo/configs

# Preview the changes, then apply them
uc-abac deploy --config-dir examples/finance_demo/configs --warehouse-id <warehouse-id> \
  --tag-management-scopes '*' --privilege-management-scopes '*' --dry-run
uc-abac deploy --config-dir examples/finance_demo/configs --warehouse-id <warehouse-id> \
  --tag-management-scopes '*' --privilege-management-scopes '*'
```

See the [quick start](https://uc-declarative-abac.readthedocs.io/en/latest/getting-started/quickstart.html)
for authentication options, and [GitHub Actions](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/github-actions.html)
to deploy from CI.

## Where did everything go?

This README used to hold the full reference. It now lives on the documentation site:

| Topic | Page |
|---|---|
| Installation and quick start | [Getting started](https://uc-declarative-abac.readthedocs.io/en/latest/getting-started/overview.html) |
| Definitions, resources, `$ref` overrides, template variables | [Concepts](https://uc-declarative-abac.readthedocs.io/en/latest/concepts/definitions-and-resources.html) |
| Catalogs, schemas, tables, volumes, functions, groups, governed tags, domains | [Configuration reference](https://uc-declarative-abac.readthedocs.io/en/latest/configuration/catalogs.html) |
| Mask, filter, and grant policies | [Policies](https://uc-declarative-abac.readthedocs.io/en/latest/configuration/policies/index.html) |
| Feature scopes | [Feature scopes](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/feature-scopes.html) |
| Authentication and required permissions | [Authentication](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/authentication.html) |
| Settings file, environment variables, system catalog proxy | [Settings](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/settings.html) |
| GitHub Actions (deploy, validate, dump) | [GitHub Actions](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/github-actions.html) |
| Deployment semantics and drift | [Deployment semantics](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/deployment-semantics.html) |
| Dumping current state | [Dumping current state](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/dumping-state.html) |
| CLI flags and exit codes | [CLI reference](https://uc-declarative-abac.readthedocs.io/en/latest/reference/cli.html) |
| Deprecated flags and inputs | [Deprecations](https://uc-declarative-abac.readthedocs.io/en/latest/reference/deprecations.html) |

## Examples and contributing

- [`examples/finance_demo`](examples/finance_demo/) is a complete, deployable-from-scratch
  governance project to copy into your own repo.
- See [CONTRIBUTING.md](CONTRIBUTING.md) to report issues or contribute changes.

---

UC Declarative ABAC is not an official Databricks product. Databricks and Unity Catalog are
trademarks of Databricks, Inc.
