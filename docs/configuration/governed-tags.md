(governed-tags)=

# Governed tags

Governed tags specify a tag name with an enforced set of allowed values. They are defined under `resources: governed_tags:` (not definitions) because they are account-level singletons. All governed tags should be created through this framework.

## Fields

**`name`**: The governed tag key. The dictionary key is used if `name` is not provided.

**`description`**: A human-readable description of the governed tag's purpose. `comment` is still accepted as a backward-compatible alias on input; see {ref}`deprecations`.

**`allowed_values`**: The fixed list of values that can be assigned to this tag. ABAC policies reference these tag key-value pairs to determine which columns to mask, which rows to filter, or which objects to grant access on.

**`assigners`**: A list of principals (users, groups, or service principals by display name) who are permitted to assign the tag to Unity Catalog objects. Principals listed here receive the `ASSIGN` role on the tag policy; those not listed have it revoked. Omitting `assigners` leaves the tag's existing assigners untouched; an explicit empty list `[]` removes all of them. This is useful for letting users test tag assignments in `dev` catalogs that aren't governed by this framework; a governed tag assigned by hand to an object that *is* governed is reverted on the next run. Assigners are only managed on tags declared in config; tags that exist in the account but not in config keep their existing assigners.

**`auto_tagging_enabled`**: (optional) Set to `true` to have Data Classification automatically apply this tag to the columns it detects, in every catalog that also sets `auto_tagging_enabled: true` (see {ref}`catalogs`). The tag is declared in config only to opt it in, so this works for system tags such as `class.email_address`; omit `assigners` to leave the tag's existing assigners untouched.

```{note}
Built-in classes use the system `class.*` governed tags. Any other governed tag needs a matching [custom classifier](https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-classification-custom-classifiers), created first in the Data Classification UI; otherwise enabling auto-tagging with that tag fails.
```

## Samples

```{code-block} yaml
:caption: resources/governed_tags/pii.yaml

resources:
  governed_tags:
    pii:
      name: pii
      description: Personally identifiable information tag
      allowed_values:
        - name
        - address
        - drivers_license
      assigners:
        - account users
```

```{code-block} yaml
:caption: resources/governed_tags/class/email.yaml

resources:
  governed_tags:
    class|email_address:
      name: class.email_address
      auto_tagging_enabled: true
```

```{code-block} yaml
:caption: resources/governed_tags/classification.yaml

resources:
  governed_tags:
    classification:
      name: classification
      description: Data classification level
      allowed_values:
        - public
        - internal
        - confidential
        - restricted
      assigners:
        - data_governance_team
        - john.smith@company.com
        - sp_data_governor
```

Once a tag policy is created, you can apply it to tables, columns, schemas, and other UC objects via the `tags:` field on any definition or resource. ABAC policies then match against these tag key-value pairs to enforce masking, filtering, or grants.

## Deletion scope

The `--governed-tag-deletion-scopes` feature gate makes config authoritative over governed tags: any tag present in UC but absent from config and matching the deletion scope is deleted. **This has a high blast radius** because deleting a tag policy orphans every object assigned that tag key across the account.

The engine logs the list of tags slated for deletion and requires interactive confirmation unless `--force` is set. System-managed governed tags (any tag key containing a `.`, e.g., `class.email_address`, `system.certification_status`) are never deleted. System tags likewise are never created or updated: only their assigners are managed.

**Config errors**: Declaring a `.`-named governed tag with `allowed_values` is a config error. Declaring a system-managed tag that doesn't already exist in the account fails the run.

## Reconciliation order

Governed tags are reconciled before tag assignments and policy creation, so new tag keys exist in the account before policies reference them.
