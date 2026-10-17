(domains)=

# Discovery domains

Discovery domains are declared explicitly under `resources.domains`. Each domain references a governed tag, whose key determines the domain hierarchy. A key such as `finance` creates a top-level domain; `finance/orders` creates an `orders` subdomain beneath it. The referenced governed tag may be declared in the same config or already exist in the account. Only the `domain` or `domain/subdomain` form is accepted, and a subdomain's root must be another governed tag or an existing Discovery domain.

## Metadata

Alongside the governed tag, a domain may set presentation metadata:

- **`description`**: The domain's description. When omitted, it falls back to the referenced governed tag's description.
- **`subtitle`**: A short tagline (max 280 characters).
- **`draft`**: Mark the domain as a draft.
- **`icon`**: A `name` from the Databricks icon set (e.g., `BANK`, `ROCKET`, `SNOWFLAKE`) plus an optional hex `color`.
- **`business_owners`**: A list of principal display names (users, groups, or service principals) to set as the domain's business owners.
- **`technical_owners`**: A list of principal display names to set as the domain's technical owners.

`subtitle`, `draft`, `icon`, `business_owners`, and `technical_owners` are managed only when supplied: an attribute left out of config is left untouched. For the owner lists specifically, a supplied list (including an empty list) is authoritative. An empty list clears all owners; a populated list reconciles to exactly those principals.

## Sample

```yaml
resources:
  governed_tags:
    finance:
      description: Finance data domain
    finance/orders:
      description: Order processing subdomain
  domains:
    finance:
      governed_tag: finance
      description: Curated finance datasets for the analytics org.
      subtitle: Financial data assets
      draft: false
      icon:
        name: BANK
        color: "#1B5E20"
      business_owners:
        - finance-stewards
      technical_owners:
        - data-platform-engineers
    finance-orders:
      governed_tag: finance/orders
```

Deploy with:

```bash
uc-abac deploy --config-dir ./configs --warehouse-id <id> \
  --domain-creation-scopes '*' --domain-modification-scopes '*'
```

## Feature scopes

Domain management has three independent gates:

Creation (`--domain-creation-scopes`)
: Creates missing domains declared under `resources.domains` that match the scope, by governed-tag key. Missing domains are created parent-first. Independent of `--domain-modification-scopes`, so a domain outside the creation scope is never created even when it matches the modification scope.

Metadata updates (`--domain-modification-scopes`)
: Updates the metadata (`description`, `subtitle`, `draft`, `icon`, `business_owners`, `technical_owners`) of matching domains declared under `resources.domains` that already exist, by governed-tag key. Independent of `--domain-creation-scopes`; it does not create missing domains.

Deletion (`--domain-deletion-scopes`)
: Makes matching domain existence authoritative over `resources.domains`. A matching actual domain absent from that block is deleted. The scope is independent of creation and modification; it activates domain state discovery and deletion without enabling creates or updates. Deletions run child-first and require confirmation unless `--force` is set. `--force` only skips the prompt; it never authorizes deleting Glossary pages, so a domain that contains them is rejected safely.

All three use the flat scope grammar, matching by governed-tag key: `*` for all, a trailing `*` for a prefix (`finance*`), or an exact key. See {ref}`feature-scopes`.

An owner name that cannot be resolved fails the run. An unresolvable owner already on a domain in the workspace is reported as a non-fatal warning and skipped (suppressible with `--ignore-unresolvable-principals`).
