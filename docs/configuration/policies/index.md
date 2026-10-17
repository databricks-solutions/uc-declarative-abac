(policies)=

# Policies

ABAC policies enforce fine-grained access control on objects in Unity Catalog. Three types cover different use cases:

- **`mask`**: applies a function to columns, letting you redact or transform sensitive data per user
- **`filter`**: applies a row-filter function to tables, controlling which rows a user can see
- **`grant`**: assigns privileges on objects to principals, with optional expiry

Attach policies to any catalog, schema, or table by declaring a `policies:` list on that object. Each entry is either an inline policy or a reference to a policy definition (`$defs/policies/<key>`, or `$ref: $defs/policies/<key>` with overrides). Reusable policy definitions live under `definitions: policies:`, keyed by the convention `<tag_key/domain>|<policy_name>` (for example `pii|mask_email_pii`).

(policy-common-fields)=

## Common fields

Every policy has these fields:

- **`name`**: the policy name (required); must be unique among policies attached to the same securable
- **`comment`**: optional description of the policy's purpose
- **`to`**: the principals the policy applies to; for **mask** and **filter**, defaults to `account users` when omitted; for **grant**, required
- **`except`**: principals exempted from the policy (mask and filter only); they see unmasked data or unfiltered rows
- **`for`**: restricts the policy to a single securable type; for **mask** and **filter**, must be `table` (the default); for **grant**, can be `catalog`, `schema`, `table`, or `volume`

Match conditions (`has_tags`, `has_any_of_tags`, `has_none_of_tags`, and attribute predicates) gate the policy on tagged resources or request context. See {ref}`policy-match-conditions` for details.

## What you'll find on each page

- **{ref}`policy-match-conditions`**: how to use tags and attributes to scope policies to the objects or requests they apply to
- **{ref}`policy-columns`**: column matching and extraction for mask and filter policies
- **{ref}`mask-and-filter-policies`**: the `function` field, inline function definitions, and mask/filter examples
- **{ref}`grant-policies`**: privileges, expiry, and cascade rules for grant policies

```{toctree}
:maxdepth: 2

match-conditions
columns
mask-and-filter
grant
```
