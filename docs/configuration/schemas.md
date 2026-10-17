(schemas)=

# Schemas

Schema definitions capture the shape of a schema: name, comment, owner, tags, policies, and RFA destinations. Each schema definition lists the tables, volumes, functions, and/or policies it contains as `$ref`/`$defs` entries. A catalog definition references which schemas to include; the engine creates each schema and its listed children inside the owning catalog.

```{code-block} yaml
:caption: definitions/operations/schemas/sales/sales.yaml

definitions:
  schemas:
    operations|sales:
      name: sales
      comment: Sales and revenue datasets
      owner: sales_engineering
      tags:
        operations: ~
      policies:
        - $defs/policies/domain|grant_read_on_sales
      tables:
        - $defs/tables/operations|sales|orders
```

```{code-block} yaml
:caption: definitions/people/schemas/hr/hr.yaml

definitions:
  schemas:
    people|hr:
      name: hr
      comment: HR data (restricted)
      owner: hr_analytics
      rfa_destinations:
        - hr-access@company.com
      tags:
        people: ~
```

```{code-block} yaml
:caption: definitions/platform/schemas/landing/landing.yaml

definitions:
  schemas:
    platform|landing:
      name: landing
      comment: Landing zone for raw data
      owner: data_platform_team
      tags:
        platform: ~
        zone: landing
      volumes:
        - $ref: $defs/volumes/platform|landing|files
          owner: hr_analysts
```

```{code-block} yaml
:caption: definitions/platform/schemas/shared/shared.yaml

definitions:
  schemas:
    platform|shared:
      name: shared
      comment: Shared functions and utilities
      owner: data_platform_team
      tags:
        shared: ~
      functions:
        - $defs/functions/platform|shared|mask_pii_email
```

When referencing a schema definition from a resource with a different catalog, use the `catalog_name` field:

```{code-block} yaml
:caption: resources/catalogs/platform_prod/schemas/shared/shared.yaml

resources:
  schemas:
    platform|shared_prod:
      $ref: $defs/schemas/platform|shared
      catalog_name: platform_prod
```
