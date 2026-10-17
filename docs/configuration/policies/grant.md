(grant-policies)=

# Grant policies

Grant policies assign privileges on securable objects (catalogs, schemas, tables, or volumes) to principals. Unlike mask and filter policies, grants require a `to` field and support an optional `expiry_date`.

(grant-privileges)=

## Privileges

The `privileges` field lists the Unity Catalog privileges to assign. You can use concrete privilege names or four shorthand abstractions that expand to fixed sets of privileges.

### Concrete privileges

These are valid UC privilege names:

`select`, `modify`, `create_table`, `create_schema`, `create_function`, `create_volume`, `use_catalog`, `use_schema`, `read_volume`, `write_volume`, `execute`, `refresh`, `create_materialized_view`, `create_model`, `create_model_version`, `create_feature`, `read_feature`, `browse`, `read_metadata`, `all_privileges`, `external_use_schema`, `manage`

### Privilege abstractions

Four abstractions expand to fixed sets of concrete privileges:

```{list-table}
:header-rows: 1
:widths: 20 60

* - Abstraction
  - Expands to
* - `read`
  - `select`, `read_volume`, `execute`
* - `write`
  - `modify`, `write_volume`, `refresh`
* - `use`
  - `use_catalog`, `use_schema`
* - `create`
  - `create_table`, `create_schema`, `create_function`, `create_volume`, `create_materialized_view`, `create_model`, `create_model_version`
```

Abstractions and concrete privileges can be mixed in the same list. Expansion is flat (not aware of the securable type). Each expanded privilege then flows through a compatibility filter based on the securable type; for example, `read` on a table-matched policy emits only `SELECT`, because the volume-specific and function-specific entries don't apply to tables. The `use_catalog`/`use_schema` cascade below applies to expanded privileges too.

(grant-for-field)=

## The `for` field

For grant policies, `for` restricts the policy to a securable type. It may be `catalog`, `schema`, `table`, or `volume`. When set, every listed privilege must be applicable to that type or config load fails. For example, `READ_VOLUME` and `WRITE_VOLUME` only apply to volumes.

(grant-tag-scoping)=

## Tag scoping by attachment level

When a grant policy is attached at a given level (catalog, schema, or table), the optional `has_tags` property scopes the grant to match only objects at that level or within it:

- A policy on a **catalog** matches the catalog and objects within it (schemas, tables, volumes)
- A policy on a **schema** matches the schema and its children (tables, volumes)
- A policy on a **table** matches the table only

If multiple tags are specified, the policy applies only to objects carrying **all** of them (AND semantics). Use `has_any_of_tags` to match objects carrying **any one** of the listed tags (OR semantics); specifying both restricts to objects matching all `has_tags` **and** at least one `has_any_of_tags`.

Omitting tag predicates from a grant policy applies the privileges directly to the object the policy is attached to, regardless of matching.

(grant-use-cascade)=

## USE_CATALOG and USE_SCHEMA cascade

When a grant policy matches a child securable and lists `use_catalog` or `use_schema`, the privilege is emitted against the correct parent securable rather than the matched child:

- A `use_catalog` privilege on a policy matching a schema, table, or volume is emitted on the containing **catalog**
- A `use_schema` privilege on a policy matching a table or volume is emitted on the containing **schema**

This cascade is bounded by the policy's attachment level. A policy attached at a schema cannot hand out `use_catalog` on its parent catalog (outside the policy's scope), and a policy attached at a table cannot hand out `use_catalog` or `use_schema` on its ancestors. To grant traverse privileges above the attachment level, attach a separate grant policy at that higher level or use a tagless policy at that level.

(grant-expiry-date)=

## Expiry date

Grant policies support an optional `expiry_date` field (ISO 8601 date: `YYYY-MM-DD`) after which the grant is automatically revoked. The current date is computed in the `timezone` setting (UTC by default). See {ref}`settings` for timezone configuration.

For expiry dates to take effect automatically, schedule regular runs of the deploy command. See {ref}`deployment-semantics` for details on scheduling and deployment.

```{note}
The expiry date is evaluated only when the engine runs. If a grant has passed its expiry date but the deploy command has not run, the grant remains in place until the engine revokes it on the next run.
```

(grant-read-metadata)=

## read_metadata privilege

```{note}
`READ METADATA` grants view-only access to an object's owner-visible metadata (permissions, row filters, column masks, and ABAC policies) without the ability to modify it or read its data. This privilege is rolling out as a preview. If it is not enabled automatically in your workspace, a workspace admin must switch it on from the **Previews** page (workspace username menu > **Previews**) before a grant will apply. See [Manage Databricks previews](https://learn.microsoft.com/en-us/azure/databricks/admin/workspace-settings/manage-previews).
```

(grant-example)=

## Example

```{code-block} yaml
:caption: definitions/policies/business_area/grant_read_on_sales.yaml

definitions:
  policies:
    business_area|grant_read_on_sales:
      name: grant_read_on_sales
      comment: Grant sales team access to sales data (until May 2026)
      type: grant
      has_tags:
        business_area: sales
      privileges:
        - read
      for: tables
      to:
        - data_engineers
        - sales_team
        - sp_sales_job_runner
      expiry_date: 2026-05-01
```

This policy grants `select`, `read_volume`, and `execute` privileges to three principals on all tables tagged `business_area: sales`. The grant expires on 2026-05-01.
