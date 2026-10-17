(policy-columns)=

# Policy columns

(policy-column-basics)=

## Column slots

Mask and filter policies can specify a `column` (single) or `columns` (ordered list). Each column is a **slot** passed as an argument to the policy `function` in declaration order, so the list must match the function's parameter signature. Three kinds of slots exist:

### Alias column

An **alias** column names a table column via a local alias used within the policy. It has:

- **`alias`**: the local name (required)
- **`has_tags`** / **`has_any_of_tags`** / **`has_none_of_tags`**: optional tag-match block

If no tag block is given, the column matches every column via `MATCH COLUMNS TRUE` (the secure-by-default pattern), where a schema-level mask gated on a `WHEN` clause (for example `review_status = pending`) masks all columns until a reviewer clears them.

For **mask** policies, the **first** column in the list must be an alias; it becomes `ON COLUMN <alias>` in the generated SQL (the column the mask is applied to) and is passed as the first function argument.

### Constant column

A **constant** column passes a static value to the function, not a table column:

- **`constant`**: the value (required)

Useful for parameterising a shared masking/filtering function per policy (for example, a per-policy replacement string).

### Expression column

An **expression** column reads a {term}`governed tag` value at query time and passes it as a function argument. **Requires DBR 18 LTS or later.** The expression uses one of two tag-introspection functions:

```yaml
expression: get_column_tag_value
arguments:
  alias: <alias_name>        # must be an alias column declared in the same policy
  tag: <tag_key>             # must be a governed tag key
```

Renders as `get_column_tag_value(<alias>, '<tag_key>')` (the value of `<tag_key>` on the matched column named by `<alias>`).

```yaml
expression: get_tag_value
arguments:
  tag: <tag_key>             # must be a governed tag key
```

Renders as `get_tag_value('<tag_key>')` (the value of a securable-level `<tag_key>` on the table, schema, or catalog).

The tag key must be non-empty and governed (validated like `has_tags` keys; an ungoverned key drops the policy at config load).

(policy-column-example)=

## Example

This mask policy uses three columns:

```yaml
name: mask_pii
type: mask
columns:
  - alias: pii                    # the first alias is the masked column (ON COLUMN pii)
    has_tags:
      pii_type: '*'
  - expression: get_column_tag_value  # → get_column_tag_value(pii, 'pii_type')
    arguments:
      alias: pii
      tag: pii_type
  - constant: REPLACEMENT_VALUE   # → constant argument
function: platform.abac.mask_by_pii_type
```

The function receives three arguments in order: the matched column, the tag value, and the constant.

(policy-secure-by-default)=

## Secure-by-default pattern

Omitting the tag block on an alias column matches every column: `MATCH COLUMNS TRUE`. This is the secure-by-default pattern used when you want a schema-level mask to apply to all columns except those explicitly cleared by a reviewer:

```yaml
name: mask_schema_pending_review
type: mask
for: tables
column:
  alias: any_column             # no tag block: matches every column
has_tags:
  review_status: pending
function: platform.abac.mask_redacted
```

This will mask all columns on tables tagged `review_status: pending` until the tag is removed.
