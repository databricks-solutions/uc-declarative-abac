(overview)=

# Overview

UC Declarative ABAC lets you manage your Databricks Unity Catalog governance model as declarative YAML files. Instead of manually managing grants, tags, and policies in the workspace, you describe your ABAC (Attribute-Based Access Control) model once in version-controlled YAML. The engine reads your configs, queries the current UC state, computes a diff, and applies only the changes needed to bring UC in line with your declared intent.

## Definitions vs resources

Configs are split into two namespaces:

- **Definitions** are environment-agnostic, reusable templates for catalogs, schemas, tables, volumes, functions, and policies. You write a definition once, version it, and reuse it across environments.
- **Resources** are concrete, deployable instances (catalogs, governed tags, groups) that compose definitions into real UC objects deployed to your workspace.

Definitions define *what exists*; resources define *where* it gets deployed.

```{note}
Definitions are optional. You can define your entire governance directly under `resources:` without using `definitions:` at all. Use definitions only when you have repeated structure (for example, the same ABAC policy applied across multiple catalogs, or schemas replicated across dev, test, and prod environments).
```

## How it works

| Use case | Flow |
|----------|------|
| **Column masking** | Policy definitions with `type: mask` create Unity Catalog ABAC masking policies that apply a function to tagged columns. |
| **Row filtering** | Policy definitions with `type: filter` create UC ABAC row-filter policies using the referenced function. |
| **GRANTs** | Policy definitions with `type: grant` compute grants from tag mappings and execute the corresponding `GRANT` and `REVOKE` statements. |
| **UC objects and tags** | Catalog resources compose schema, table, volume, and function definitions. The engine creates and tags them in each target catalog. |

You maintain YAML as the source of truth; the engine turns it into UC objects and permissions.

## Architecture

```{figure} ../_static/architecture.svg
:alt: Architecture of UC Declarative ABAC. The uc-abac CLI and GitHub Actions run the engine. The engine loads and resolves the YAML configs, compiles the desired state, fetches the actual state from Unity Catalog, diffs the two with principal resolution, and executes the changes. The dump command writes the actual state, attributed to config files, to tables that ABAC Policy Explorer reads.
:width: 100%

The `uc_abac` engine, its entry points, and how ABAC Policy Explorer fits in.
```

The `uc-abac` CLI and the GitHub Actions (`validate`, `deploy`, `dump`) run the same engine, coordinated by `orchestrator.py`:

1. **Config pipeline** (`configs/`): discovers the YAML files, resolves `$ref`, `$vars`, and overrides, and validates one `ResourcesConfig`, with every entry stamped with the file that declares it. `uc-abac validate` stops here.
2. **Compilers** (`<domain>/compiler.py`): turn the config into the desired state of each domain, naming principals by display name.
3. **Actual state fetch** (`helpers/`): reads the current state from Unity Catalog and the workspace, in parallel, naming principals by identifier.
4. **Differs** (`<domain>/differ.py`): resolve the principals on both sides, then compute the changes needed.
5. **Executors** (`<domain>/executor.py`): run the SQL and SDK calls for those changes, within the {ref}`feature scopes <feature-scopes>`. With `--dry-run`, they log the changes instead.
6. **Dumper** (`dumper/`): for `uc-abac dump`, writes the actual state to tables in a target schema, attributing each row to the config file that declares it.

Each domain (governed tags, tags, securables, privileges, policies, groups, and domains) has its own compiler, differ, and executor. {ref}`policy-explorer` is a separate package, `abac_viewer`, deployed as a Databricks App. It reads the dump tables and depends on the engine only for its privilege and securable type definitions (`uc_abac.types`).

## Next steps

- {ref}`quickstart` to get up and running in minutes
- {ref}`authentication` for deployment credential setup
- {ref}`definitions-and-resources` to understand the structural building blocks
- {ref}`catalogs` and the rest of the configuration reference for every object you can declare
