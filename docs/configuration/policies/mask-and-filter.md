(mask-and-filter-policies)=

# Mask and filter policies

(mask-filter-function-field)=

## The `function` field

Both mask and filter policies require a `function` field, which is either a fully qualified Unity Catalog function name or an inline function definition. Unity Catalog applies this function to the matched columns or rows at query time.

### Existing UC function by name

Reference an existing UC function by its full name:

```yaml
function: platform.abac.mask_email
```

A partially qualified name is completed from the policy's own catalog and schema:

- A fully qualified `catalog.schema.fn` is left unchanged.
- `shared.mask_email` becomes `<catalog>.shared.mask_email`.
- A bare `mask_email` becomes `<catalog>.<schema>.mask_email`. On a catalog-level policy there is
  no schema to prepend, so it falls back to the catalog's `default` schema, the same place inline
  catalog-level functions are deployed.

### Inline function definitions

Define the function inline in the policy itself. The engine moves inline definitions into the enclosing **schema**, or the **catalog's `default` schema** if the policy is attached at the catalog level. It then rewrites the policy's `function` field to the synthesised full name. The default synthesised name is `abac_<policy_name>`.

You can override this with `catalog_name` and `schema_name`:

```yaml
function:
  catalog_name: custom_catalog
  schema_name: custom_schema
  parameters:
    - name: col_value
      type: string
  return: 'CONCAT(col_value, "_MASKED")'
```

A filter policy's inline function can define its body with {ref}`RLS mapping rules <functions-rls-mapping-rules>` instead of `return`.

If this results in two functions with the same name in the same catalog and schema, config load fails with a duplicate functions error. When several policies use the same reusable function definition inline via `$defs/functions/<key>`, override the function `name` on each to keep them distinct.

(mask-filter-for-field)=

## The `for` field

For mask and filter policies, `for` must be `table` (the default). These policy types only apply to table-level data.

(mask-filter-examples)=

## Examples

### Mask email PII

```{code-block} yaml
:caption: definitions/policies/pii/mask_email_pii.yaml

definitions:
  policies:
    pii|mask_email_pii:
      name: mask_email_pii
      comment: Mask email PII from all users except account admins
      type: mask
      column:
        alias: email
        has_tags:
          pii: email
      function: platform.abac.mask_email_pii
      to:
        - account users
      except:
        - pii_viewers
```

### Mask retail-segment customer names

```{code-block} yaml
:caption: definitions/policies/pii/mask_retail_segment_customer_names_pii.yaml

definitions:
  policies:
    pii|mask_retail_segment_customer_names_pii:
      name: mask_retail_segment_customer_names_pii
      comment: Mask retail-segment customer names (not commercial-segment) from all users except account admins
      type: mask
      has_tags:
        domain: customer
      columns:
        - alias: name
          has_tags:
            pii: '*'
            class.name: '*'
        - alias: segment
          has_tags:
            segment: '*'
      function: platform.abac.mask_retail_segment_customer_names_pii
      to:
        - account users
      except:
        - customer_pii_viewers
```

### Mask email with a fixed value

An inline mask function parameterised by a constant replacement value. The first column (alias) is the masked column and the constant is passed as the second function argument, so `jane@example.com` is shown as `REDACTED@example.com`:

```{code-block} yaml
:caption: definitions/policies/pii/mask_email_redacted.yaml

definitions:
  policies:
    pii|mask_email_redacted:
      name: mask_email_redacted
      type: mask
      columns:
        - alias: email
          has_any_of_tags:
            pii: email
            class.email: '*'
        - constant: REDACTED
      function:
        parameters:
          - name: email
            type: string
          - name: replacement
            type: string
        return: CONCAT(replacement, SUBSTRING(email, INSTR(email, '@')))
      to:
        - account users
```

### Filter by region

Users see only the rows for their region, defined with an {ref}`RLS mapping rule <functions-rls-mapping-rules>`; members of `global_readers` see every region:

```{code-block} yaml
:caption: definitions/policies/region/filter_by_region.yaml

definitions:
  policies:
    region|filter_by_region:
      name: filter_by_region
      comment: Users can only see records for their region
      type: filter
      column:
        alias: region
        has_tags:
          region: '*'
      function:
        parameters:
          - name: region
            type: string
        match_rules:
          - rls_mapping:
              AFRICA: africa_readers
              AMERICA: america_readers
              EUROPE: europe_readers
              ASIA: asia_readers
              MIDDLE EAST: middle_east_readers
              '*': global_readers
      except:
        - account admins
```

(mask-filter-deletion)=

## Deletion

Mask and filter policy deletion is covered by the policy deletion scope. See {ref}`feature-scopes` and {ref}`deployment-semantics`.
