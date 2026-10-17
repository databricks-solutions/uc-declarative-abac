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

## Next steps

- {ref}`quickstart` to get up and running in minutes
- {ref}`authentication` for deployment credential setup
- {ref}`definitions-and-resources` to understand the structural building blocks
- {ref}`catalogs` and the rest of the configuration reference for every object you can declare
