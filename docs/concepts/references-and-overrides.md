(references-and-overrides)=

# References and overrides

## References and `$defs`

Definitions are referenced using the `$ref` keyword with a `$defs/<type>/<key>` target. This syntax is inspired by JSON Schema's `$defs` and `$ref` keywords. You can reference definitions inline as bare strings or as structured `$ref` objects:

```yaml
# Inline string reference
tables:
  - $defs/tables/operations|sales|orders

# Structured $ref with overrides (see below)
schemas:
  - $ref: $defs/schemas/operations|sales
    name: sales_staging
```

The `<type>` segment is simply the key the definition is declared under in `definitions:`; it is not a fixed list. Any part of a config can be a definition: catalogs, schemas, tables, volumes, functions, and policies, but also columns, function parameters, filter rules, tags, groups, governed tags, domains, or any other value. Reference it wherever that value is accepted. A definition whose body is a list (for example, a function's `parameters`) must be referenced with the inline string form, not a `$ref` object.

## Overrides

Any `$ref` entry can include additional fields alongside the reference. These fields override the corresponding values from the definition, letting you customize a single instance without modifying the shared definition. For example, you can override `owner`, `rfa_destinations`, `comment`, `tags`, or `function` on a per-catalog or per-resource basis. Unspecified fields fall back to the definition.

Overrides also support nested references: you can nest `$ref` entries within an override to further customize child objects. For example, overriding a schema's `tables` list with specific table references that themselves carry overrides:

```{code-block} yaml
resources:
  catalogs:
    operations_test:
      name: operations_test
      comment: TEST Operations catalog
      schemas:
        - $ref: $defs/schemas/operations|sales
          name: sales_staging
          tables:
            - $ref: $defs/tables/operations|sales|orders
            - $ref: $defs/tables/operations|sales|quotes
              comment: This table only exists in TEST
```

### Deep-merge rules

By default, overrides recursively deep-merge into the definition:

- **Maps merge key-wise**: Override keys take precedence; unspecified keys fall back to the definition. For example, you can override a single tag and the other tags from the definition are preserved.
- **Lists of identifier-bearing items merge by `name` (or `alias`)**: Items in the override that match an item in the definition by identifier are recursively merged with it; unmatched override items are appended; unmatched definition items are preserved. This lets you add a new table to a schema definition's `tables` list, or tweak a single column, without re-listing every existing entry.
- **Lists of primitives are unioned with dedupe**: Useful for `privileges`, where you want to add `MODIFY` to a definition's `[SELECT]` without dropping `SELECT`.
- **Other shapes (mixed items, type mismatch, items without identifiers) fall back to replace**: The override wins entirely. There's no sensible way to align items.

#### Merge example

```{code-block} yaml
# Definition
definitions:
  schemas:
    operations|sales:
      name: sales
      tags:
        domain: operations
        pii: "true"
      tables:
        - name: orders
          comment: Orders table
        - name: quotes
          comment: Quotes table

# Resource: override merges, doesn't replace
resources:
  catalogs:
    operations_test:
      schemas:
        - $ref: $defs/schemas/operations|sales
          tags:
            pii: "false"
            env: test                     # 'domain' preserved; 'pii' updated; 'env' added
          tables:
            - name: quotes
              comment: TEST quotes table  # merges with definition's 'quotes'
            - name: leads
              comment: Leads table        # appended; 'orders' from def is preserved
```

### Legacy shallow-replacement strategy

The legacy shallow-replacement behaviour (where any override of a list or map replaces it in its entirety) is available via `--ref-override-strategy replace`, but that flag is deprecated and slated for removal. Using `replace` logs a deprecation warning. Migrate configs to rely on the default `merge` behaviour and omit the flag. See {ref}`deprecations` for details.
