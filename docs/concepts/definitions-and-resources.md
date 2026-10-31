(definitions-and-resources)=

# Definitions and resources

## What you can define in YAML

Your YAML configs contain two main object types:

### Definitions (reusable templates)

Definitions are environment-agnostic templates that you can reference and reuse across multiple catalogs and environments. Any part of a config can be a definition, under any type name you choose (see {ref}`references-and-overrides`). The most common are:

- **Catalog definitions**: Top-level templates that list the schemas and policies a catalog should contain. Define the canonical shape of a catalog once, then have a catalog resource `$ref` the definition and override only what differs between environments.
- **Schema definitions**: Schema templates listing their child tables, volumes, and functions.
- **Table definitions**: Table definitions tied to a schema definition.
- **Volume definitions**: Volume definitions tied to a schema definition.
- **Function definitions**: UDF definitions with parameters and return expressions.
- **Rule definitions**: reusable {ref}`RLS mapping rules <functions-rls-mapping-rules>` for row filter functions, under `definitions: rules:`.
- **Policy definitions**: ABAC policies for column masking, row filtering, and grants.
- **Other reusable fragments**: anything else you repeat, such as tag maps, columns, function parameters, groups, governed tags, or domains.

### Resources (deployed UC objects)

Resources are the concrete instances that get deployed to Unity Catalog:

- **Groups**: account groups, their members, and their assumers. Creation, membership reconciliation, and deletion are each enabled by their own scope; see {ref}`groups`.
- **{term}`Governed tags <governed tag>`**: Enforced usage rules for UC governed tags with allowed values, allowed principals, and comments. (See {ref}`governed-tags`.)
- **Catalogs**: Usually a thin `$ref` to a catalog definition with optional overrides (for example, a different `name` or `tags` for a test vs prod environment). Can also be written fully inline when no reuse is needed.
- **Schemas, tables, volumes, functions, mask/filter ABAC policies**: Concrete instances that can reference relevant definitions. Generally you shouldn't need to declare these at the resource level because they're pulled in transitively via the catalog definition. Both options are supported.

### Metadata on all objects

Every object can have:

- **Owners**: Set or update owners on catalogs, schemas, tables, volumes, and functions.
- **Comments**: Manage descriptions on UC objects, including columns.
- **Tags**: Key-value or valueless tags (using `~`) applied to any object.
- **RFA destinations**: Configure where access requests are sent for governed objects.

## YAML config structures

Configs use dictionaries keyed by definition IDs. The recommended convention is to use pipe-delimited keys that mirror the Unity Catalog path of the object. For example: `my_catalog` for a catalog, `my_catalog|sales` for a schema, `my_catalog|sales|orders` for a table. This matches the Databricks Terraform provider's composite resource IDs (such as `<metastore_id>|<name>` for UC connections). For reusable, catalog-agnostic definitions (typically policies and shared functions), a `<tag_key/domain>|<name>` style works well, such as `pii|mask_pii`. The pipe delimiter is a convention only and is not enforced by the engine: keys can be any valid YAML string.

### Key conventions by type

```{list-table}
:header-rows: 1
:widths: 25 20 30

* - Type
  - Convention
  - Example
* - Catalogs
  - `<catalog_name>`
  - `operations`
* - Schemas
  - `<catalog_name>|<schema_name>`
  - `operations|sales`
* - Tables
  - `<catalog_name>|<schema_name>|<table_name>`
  - `operations|sales|orders`
* - Volumes
  - `<catalog_name>|<schema_name>|<volume_name>`
  - `operations|landing|raw_events`
* - Functions (catalog-specific)
  - `<catalog_name>|<schema_name>|<function_name>`
  - `operations|shared|mask_pii_email`
* - Functions (cross-catalog, reusable)
  - `<tag_key/domain>|<function_name>`
  - `pii|mask_pii`
* - Policies (cross-catalog, reusable)
  - `<tag_key/domain>|<policy_name>`
  - `pii|mask_pii_email`
```

These keys are the stable identity for each entity and let you reference entities across files via `$defs/<type>/<key>` or `$ref: $defs/<type>/<key>` syntax (inspired by JSON Schema's `$defs` and `$ref` keywords). This syntax also supports selective config overrides (see {ref}`references-and-overrides`).

```{important}
Strict keys: Config models reject unknown keys. A field that isn't part of the schema (a typo like `has_tag` for `has_tags`, `too` for `to`, or a key placed on the wrong object type) is a hard validation error, not silently ignored. Likewise, a duplicate mapping key anywhere in a YAML file (the same policy id or tag key written twice) is a hard parse-time error.
```

A catalog, schema, table, volume, function, or mask/filter policy definition can be promoted to a concrete resource by placing it under `resources:` with a `$ref` / `$defs` reference to the definition. For catalogs this is the usual pattern. For leaf types (table, volume, function) you can also promote them directly when you need a single deployed instance outside of a catalog composition. These require `catalog_name` and `schema_name` to be set.

### Definitions

Definition configs are reusable templates for any part of a config: every UC object type (catalogs, schemas, tables, volumes, functions, and policies) as well as smaller fragments such as tags, columns, parameters, and filter rules. The recommended pattern is to structure your definitions like the UC catalog itself: one top-level `catalog` definition that composes the schemas, policies, tags, and other catalog-level metadata, and then nested schema, table, volume, and function definitions organized by catalog and schema. This keeps definitions close to the UC object they describe and makes the resource side of the config trivial, usually just a `$ref` to the catalog definition with a few overrides (for example, a name change between prod and test environments).

Cross-catalog reusable definitions (typically ABAC policies and shared functions) can live outside the catalog tree under `definitions/policies/` or `definitions/functions/` and be referenced from multiple catalogs.

The configuration reference documents each definition type in detail: {ref}`catalogs`,
{ref}`schemas`, {ref}`tables`, {ref}`volumes`, {ref}`functions`, and {ref}`policies`.
