(tables)=

# Tables

Tables are defined in a flat dictionary under `definitions: tables:`. Key convention: `<catalog_name>|<schema_name>|<table_name>`.

Row-level and column-level security are applied with tag-based ABAC policies: tag columns and tables, and let {ref}`policies` match against those tags to apply masking, filtering, and grants.

## Column-level fields

- **`name`**: the column name (required).
- **`type`**: the column data type (optional). Required to create the table or to add the column to an existing table; see {ref}`tables-creation`.
- **`comment`**: a description of the column.
- **`tags`**: key-value or valueless tags applied to the column. Useful for ABAC policies that match against tagged columns.

## Table-level fields

In addition to {ref}`common-fields` (`name`, `owner`, `comment`, `tags`, `rfa_destinations`):

- **`columns`**: list of column-level configurations (see above).
- **`policies`**: list of policy `$ref`/`$defs` entries or inline policies scoped to this table.
- **`location`**: external storage location (URI). Setting `location` on a new table makes it an external table; the `LOCATION` clause is included in `CREATE TABLE`. **External location is immutable after creation** and cannot be changed.

## Samples

```{code-block} yaml
:caption: definitions/operations/schemas/sales/tables/orders.yaml

definitions:
  tables:
    operations|sales|orders:
      name: orders
      owner: sales_engineering
      comment: Orders fact table
      location: s3://operations-external/sales/orders
      rfa_destinations:
        - sales-data@company.com
      tags:
        classification: internal
        sales: ~
      policies:
        - $ref: $defs/policies/pii|mask_pii_email
```

```{code-block} yaml
:caption: definitions/people/schemas/hr/tables/employees.yaml

definitions:
  tables:
    people|hr|employees:
      name: employees
      owner: hr_analytics_team
      tags:
        people: ~
      columns:
        - name: employee_id
          type: long
        - name: full_name
          type: string
          tags:
            pii: name
        - name: email
          type: string
          tags:
            pii: email
        - name: salary
          type: decimal(10, 2)
          tags:
            classification: confidential
```

(tables-creation)=

## Table creation and modification

Tables must declare at least one column with a `type` (for example `type: STRING`) to be created. Columns declared in config but missing from an existing table are added, provided they declare a `type`; otherwise creation fails with an error explaining the requirement.

Table-level comments are supported on managed and external tables. **Comments are not supported on views**: set the comment in the view definition instead. If a table's actual `table_type` is `VIEW`, a table-level comment change is refused with a logged error.

Column-level comments are supported on all table types. When a column is created (via `CREATE TABLE` or `ADD COLUMN`), its comment is embedded directly in that statement.

Owner updates on tables whose `table_type` is `MATERIALIZED_VIEW` or `STREAMING_TABLE` fail with a logged error. Change ownership on the pipeline instead.

These requirements are gated by {ref}`feature-scopes`: table and column creation under `--securable-creation-scopes`, and table/column comment updates under `--securable-modification-scopes`.
