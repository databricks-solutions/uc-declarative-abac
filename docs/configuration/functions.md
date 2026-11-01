(functions)=

# Functions

Functions are defined under `definitions: functions:`. Key convention: `<catalog_name>|<schema_name>|<function_name>` for catalog-specific functions (e.g., `platform|shared|mask_pii_email`), or `<tag_key/domain>|<function_name>` for cross-catalog reusable functions (e.g., `pii|mask_pii_email`).

## Core behaviour

Functions are **always engine-managed**: they are created, replaced, or updated regardless of securable feature scopes. The return type is inferred from the `return` expression; a function defined with {ref}`RLS mapping rules <functions-rls-mapping-rules>` returns a boolean. ABAC mask and filter policies can reference functions inline (by their definition) or by fully qualified UC function name.

## Samples

```{code-block} yaml
:caption: definitions/platform/schemas/shared/functions/mask_pii_email.yaml

definitions:
  functions:
    platform|shared|mask_pii_email:
      name: mask_email
      comment: Masks email for PII policy
      owner: data_platform_team
      parameters:
        - name: address
          type: string
      return: "CONCAT('***', SUBSTRING(address, -4))"
```

```{code-block} yaml
:caption: definitions/platform/schemas/shared/functions/filter_by_region.yaml

definitions:
  functions:
    platform|shared|fn_filter_by_region:
      name: fn_filter_by_region
      comment: Users can only see records from their region
      parameters:
        - name: region
          type: string
      return: |-
        (region = 'AFRICA' AND is_account_group_member('africa_users'))
        OR (region = 'AMERICA' AND is_account_group_member('america_users'))
        OR (region = 'EUROPE' AND is_account_group_member('europe_users'))
        OR (region = 'ASIA' AND is_account_group_member('asia_users'))
        OR (region = 'MIDDLE EAST' AND is_account_group_member('middle_east_users'))
```

Policies can reference functions by fully qualified name (e.g., `catalog.schema.function_name`) or by {term}`definition ID` via `$defs`. See {ref}`mask-and-filter-policies` for full details.

(functions-rls-mapping-rules)=

## RLS mapping rules

A row filter function can define its body with structured rules instead of a `return` expression. The engine renders the rules into the function's SQL body, validates every rule against the function's parameters, and resolves every principal against the account, so a misspelled group fails the deployment instead of silently hiding rows.

A function's body is either `return`, or one or both of:

- **`match_rules`**: a row is visible when **all** listed rules are true (AND semantics, like `has_tags`)
- **`match_any_of_rules`**: a row is visible when **at least one** listed rule is true (OR semantics, like `has_any_of_tags`)

When both are set they combine with AND, the same way tag predicates combine (see {ref}`policy-combined-when-clause`). Combining `return` with either field is a config error.

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

Renders as:

```{code-block} sql
(
  (region = 'AFRICA' AND is_account_group_member('africa_readers'))
  OR (region = 'AMERICA' AND is_account_group_member('america_readers'))
  OR (region = 'EUROPE' AND is_account_group_member('europe_readers'))
  OR (region = 'ASIA' AND is_account_group_member('asia_readers'))
  OR (region = 'MIDDLE EAST' AND is_account_group_member('middle_east_readers'))
  OR is_account_group_member('global_readers')
)
```

Functions defined with these rules return a boolean row predicate, so only `filter` policies may use them; a `mask` policy that references one fails config validation.

### Rule fields

Every rule is exactly one of two shapes. Two identical rules in the same list are a config error.

A **condition rule** holds a raw boolean SQL expression:

- **`condition`**: rendered wrapped in parentheses, for example `amount < 10000`

An **RLS mapping rule** maps parameter values to the principals allowed to see rows holding them:

- **`rls_mapping`** (required): a non-empty map of parameter values to a principal name or a list of principal names (a list means any of them). A `'*'` key matches every row, whatever the parameter value.
- **`parameter`**: the parameter the keys are compared with. Optional when the function has one parameter, or when the only key is `'*'`; otherwise required.
- **`operator`**: how a key is compared with the parameter (default `=`), from the list below.
- **`identity`**: how the querying user is checked against a mapped principal. `is_account_group_member` (the default) checks account group membership; `current_user` compares the querying user's username, or a service principal's application ID, with the mapped user or service principal. `is_member` is not supported, because the engine cannot resolve workspace-local groups.

### Operators

```{list-table}
:header-rows: 1

* - Operator
  - Renders as
  - Parameter type
* - `=`
  - `param = key`
  - any supported scalar type
* - `<`, `<=`, `>`, `>=`
  - `param <= key`
  - numeric, string, date, or timestamp
* - `LIKE`, `ILIKE`, `RLIKE`, `REGEXP`
  - `param LIKE key`
  - string
* - `regexp_like`, `startswith`, `endswith`, `contains`
  - `startswith(param, key)`
  - string
* - `array_contains`
  - `array_contains(param, key)`
  - `array<T>`; keys have type `T`
* - `map_contains_key`
  - `map_contains_key(param, key)`
  - `map<K, V>`; keys have type `K`
```

With `LIKE` and `ILIKE`, `%` and `_` in a key are wildcards. With the comparison operators each key is a threshold, and entries are OR-joined, which suits tiered access:

```{code-block} yaml
match_rules:
  - parameter: sensitivity_level
    operator: '<='
    rls_mapping:
      1: public_readers
      2: internal_readers
      3: confidential_readers
```

With an `int` `sensitivity_level` parameter, `internal_readers` see rows at levels 1 and 2.

### Key types

Keys are validated against the type they are compared with (the parameter type, or the element or key type for `array_contains` and `map_contains_key`) and rendered as a literal of that type, for example `'AMER'`, `42`, `TRUE`, `DATE'2026-05-02'`, or `TIMESTAMP'2026-05-02 10:00:00'`. A key may be written as a native YAML value of the matching type, or as a string that parses as that type, so `42` and `'42'` are equivalent for an `int` parameter. Two keys that render the same literal are an error. Types with no YAML equivalent, such as `binary`, `interval`, or `struct`, cannot be used as keys; use a condition rule instead.

Quote string keys that YAML would otherwise read as another type: an unquoted `NO`, `YES`, `ON`, or `OFF` is a boolean, and an unquoted `2026-05-02` is a date.

Keys may contain template variables (see {ref}`template-variables`).

### Reusing rules

Rules can be defined once under `definitions: rules:` and referenced from any function, either as a bare `$defs/rules/<key>` list item or as a `$ref` with overrides:

```{code-block} yaml
definitions:
  rules:
    user_in_region:
      rls_mapping:
        AFRICA: africa_readers
        AMERICA: america_readers
        EUROPE: europe_readers
        ASIA: asia_readers
        MIDDLE EAST: middle_east_readers

  functions:
    region|fn_filter_by_region:
      name: fn_filter_by_region
      parameters:
        - name: region
          type: string
      match_rules:
        - $defs/rules/user_in_region

    region|fn_filter_trips_by_region:
      name: fn_filter_trips_by_region
      parameters:
        - name: from_region
          type: string
        - name: to_region
          type: string
      match_any_of_rules:
        - $ref: $defs/rules/user_in_region
          parameter: from_region
        - $ref: $defs/rules/user_in_region
          parameter: to_region
```

Combining both lists, with a wildcard-only mapping in place of a hand-written `is_account_group_member` condition:

```{code-block} yaml
parameters:
  - name: region
    type: string
  - name: amount
    type: decimal(18,2)
match_rules:
  - $ref: $defs/rules/user_in_region
    parameter: region
match_any_of_rules:
  - condition: amount < 10000
  - rls_mapping:
      '*': fraud_analysts
```

Renders as:

```{code-block} sql
(
  (region = 'AFRICA' AND is_account_group_member('africa_readers'))
  OR ...
)
AND (
  (amount < 10000)
  OR (
    is_account_group_member('fraud_analysts')
  )
)
```

A `$ref` override of a function merges its rule lists like any other list (see {ref}`references-and-overrides`):

- A rule written as a `$ref` to a rule definition is merged into the definition's rule with the same `$ref`, if exactly one rule has it. For example, an override can add a key to that rule's `rls_mapping`.
- Any other rule is added to the list, unless an identical rule is already there. Adding a rule to `match_any_of_rules` widens who can see rows.
- If the `$ref` appears on several of the definition's rules (for example, one rule definition reused for two parameters), the override is ambiguous and config load fails. Redefine the function's rule lists instead.

Rules can't be removed by an override. A `$ref` to a function definition that uses `return` can't be overridden with rule lists either, because the merged function would set both.
