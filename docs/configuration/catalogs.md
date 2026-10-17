(catalogs)=

# Catalogs

Catalogs are the top-level organizational unit in Unity Catalog. Catalog definitions capture the canonical shape of a catalog, including its tags, owner, RFA destinations, catalog-level policies, and the schemas it contains.

## Definitions

Catalog definitions are keyed by catalog name (e.g., `operations`, `platform`). A catalog definition composes schemas and policies via `$ref`/`$defs` entries.

```{code-block} yaml
:caption: definitions/catalogs/operations/operations.yaml

definitions:
  catalogs:
    operations:
      name: operations
      comment: Operations catalog
      owner: data_platform_team
      location: s3://operations-managed/operations
      rfa_destinations:
        - data-governance@company.com
      policies:
        - $defs/policies/domain|grant_finance_read
        - $defs/policies/pii|mask_pii_email
      schemas:
        - $defs/schemas/operations|sales
        - $defs/schemas/operations|landing
```

The optional `location` sets the catalog's managed storage location (`MANAGED LOCATION`). It is applied only when the engine creates the catalog.

## Resources

Catalogs are deployed by placing an entry under `resources: catalogs:`. The recommended pattern is a thin `$ref` to a matching definition, with optional overrides for environment-specific values.

### Pattern 1: Thin reference with overrides

One catalog definition (above), multiple resources:

```{code-block} yaml
:caption: resources/catalogs/operations_prod.yaml

resources:
  catalogs:
    operations_prod:
      $ref: $defs/catalogs/operations
      name: operations_prod
      tags:
        env: prod
```

```{code-block} yaml
:caption: resources/catalogs/operations_test.yaml

resources:
  catalogs:
    operations_test:
      $ref: $defs/catalogs/operations
      name: operations_test
      tags:
        env: test
```

### Pattern 2: Fully inline

If you don't need reuse, skip the definition layer and declare the catalog straight under `resources:`:

```{code-block} yaml
:caption: resources/catalogs/operations_prod.yaml

resources:
  catalogs:
    operations_prod:
      name: operations_prod
      owner: data_platform_team
      tags:
        env: prod
      policies:
        - $defs/policies/pii|mask_pii_email
      schemas:
        - $defs/schemas/operations|sales
```
