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

A shared mask function reused across policies, parameterised by a constant replacement value. The first column (alias) is the masked column; the constant is passed as the second function argument:

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
      function: platform.abac.mask_with_value
      to:
        - account users
```

### Filter trips by region

A trip is visible when either endpoint is in one of the user's regions. The region mapping is written once as a {ref}`rule definition <functions-rls-mapping-rules>` and applied to each endpoint parameter with a `$ref` override:

```{code-block} yaml
:caption: definitions/policies/region/filter_trips_by_region.yaml

definitions:
  rules:
    user_in_region:
      name: user_in_region
      rls_mapping:
        AFRICA: africa_users
        AMERICA: america_users
        EUROPE: europe_users
        ASIA: asia_users
        MIDDLE EAST: middle_east_users

  policies:
    region|filter_trips_by_region:
      name: filter_trips_by_region
      comment: Users can only see high sensitivity trips to or from their region
      type: filter
      has_tags:
        trips: '*'
        sensitivity: high
      columns:
        - alias: from_region
          has_tags:
            from_region: '*'
        - alias: to_region
          has_tags:
            to_region: '*'
      function:
        parameters:
          - name: from_region
            type: string
          - name: to_region
            type: string
        match_any_of_rules:
          - $ref: $defs/rules/user_in_region
            name: user_in_from_region
            parameter: from_region
          - $ref: $defs/rules/user_in_region
            name: user_in_to_region
            parameter: to_region
      except:
        - account admins
```

(mask-filter-deletion)=

## Deletion

Mask and filter policy deletion is covered by the policy deletion scope. See {ref}`feature-scopes` and {ref}`deployment-semantics`.
