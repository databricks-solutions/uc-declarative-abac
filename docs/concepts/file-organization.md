(file-organization)=

# File organization

The recommended convention is to mirror the Unity Catalog directory structure under `definitions/catalogs/`, so each catalog, schema, table, volume, and function config file sits where you'd expect to find it in UC. Cross-catalog reusable content (policies, shared functions) lives outside the catalog tree under `definitions/policies/` or `definitions/functions/`. The resource side stays thin: typically one file per catalog that references the matching catalog definition.

## Recommended layout

```
definitions/
├── catalogs/
│   └── operations/
│       ├── operations.yaml              # catalog definition
│       └── schemas/
│           ├── sales/
│           │   ├── sales.yaml           # schema definition
│           │   ├── tables/
│           │   │   ├── orders.yaml      # table definition
│           │   │   └── quotes.yaml
│           │   ├── functions/
│           │   │   └── lookup_region.yaml
│           │   └── CODEOWNERS
│           └── landing/
│               ├── landing.yaml
│               ├── volumes/
│               │   └── raw_events.yaml
│               └── CODEOWNERS
├── policies/                            # cross-catalog reusable policies
│   ├── pii/
│   │   ├── mask_pii.yaml
│   │   └── CODEOWNERS
│   └── domain/
│       ├── grant_sales_read.yaml
│       └── CODEOWNERS
└── functions/                           # cross-catalog reusable functions (optional)
    └── pii/
        ├── mask_pii_email.yaml
        └── CODEOWNERS

resources/
├── catalogs/
│   ├── operations_prod.yaml             # thin $ref to the catalog definition
│   └── operations_test.yaml
├── governed_tags/
│   ├── pii.yaml
│   └── domain.yaml
└── groups/
    ├── data_engineers.yaml
    └── finance_analysts.yaml

CODEOWNERS
```

This folder structure is a recommendation, not enforced by the engine. The engine discovers every `.yaml` or `.yml` file under the config root and resolves references by definition key, not by file path. Keeping files where you'd expect them in a UC browser makes configs easy to navigate. Pairing each catalog definition with a matching one-line resource file is a clean split: definitions describe what exists; resources describe where it gets deployed.
