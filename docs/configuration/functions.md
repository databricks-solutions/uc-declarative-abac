(functions)=

# Functions

Functions are defined under `definitions: functions:`. Key convention: `<catalog_name>|<schema_name>|<function_name>` for catalog-specific functions (e.g., `platform|shared|mask_pii_email`), or `<tag_key/domain>|<function_name>` for cross-catalog reusable functions (e.g., `pii|mask_pii_email`).

## Core behaviour

Functions are **always engine-managed**: they are created, replaced, or updated regardless of securable feature scopes. The return type is inferred from the `return` expression. ABAC mask and filter policies can reference functions inline (by their definition) or by fully qualified UC function name.

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
