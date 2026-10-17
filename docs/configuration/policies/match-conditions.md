(policy-match-conditions)=

# Match conditions

A policy's match conditions scope it to specific objects or requests by checking tags on the resource and attributes of the request or querying principal. These render into the `WHEN` clause of the generated policy SQL.

(policy-tag-predicates)=

## Tag predicates

Tag predicates match against {term}`governed tag`s assigned to the resource:

- **`has_tags`**: an object matches if it carries **all** of the listed tags (AND semantics); `{key: value}` matches a tag with that exact value, and `{key: '*'}` matches any value for the key (presence check); multiple entries combine as AND
- **`has_any_of_tags`**: an object matches if it carries **any one** of the listed tags (OR semantics); otherwise works like `has_tags`
- **`has_none_of_tags`**: an object matches if it carries **none** of the listed tags (negation); each entry renders as NOT; available on mask and filter policies only

When both `has_tags` and `has_any_of_tags` are specified, they combine as AND-of-groups: an object must satisfy all `has_tags` **and** at least one `has_any_of_tags`. Add `has_none_of_tags` and the object must additionally satisfy none of those tags.

For **grant** policies, tag predicates scope to the securable level where the policy is attached: a policy on a schema matches the schema and its children (tables, volumes). For **mask** and **filter** policies, tag predicates scope to tagged **tables**. To match columns for masking or filtering, use {ref}`policy-columns` tag blocks instead.

(policy-context-attribute-predicates)=

## Context-attribute predicates

Context attributes gate the policy on the **request context** using a [context attribute function](https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/core-concepts#context-attribute-functions-beta) (beta), for example `request.is_on_behalf_of`, or `request.client_id` for OAuth-app requests:

- **`has_context_attributes`**: the request matches if all listed context attributes are present with the specified values (AND semantics); `{key: value}` matches an exact value, and `{key: '*'}` matches if the key is present (presence check, no empty or null)
- **`has_any_of_context_attributes`**: the request matches if **any one** listed context attribute matches (OR semantics)
- **`has_none_of_context_attributes`**: the request matches if **none** of the listed context attributes match (negation)

Available on mask and filter policies only. Empty and null values are rejected at config load; use `'*'` for a presence check.

(policy-identity-attribute-predicates)=

## Identity-attribute predicates

Identity attributes gate the policy on attributes of the **querying principal** using an [identity attribute function](https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/core-concepts#identity-attribute-functions-beta) (beta). Each `key: value` entry renders as `has_identity_attribute_value('key', 'value')`. **Available on mask policies only:**

- **`has_identity_attributes`**: the principal matches if all listed identity attributes are present with the specified values (AND semantics); `{key: value}` requires an exact, non-empty key and value; **no wildcard** is supported, so every entry must specify both; multiple entries combine as AND
- **`has_any_of_identity_attributes`**: the principal matches if **any one** listed identity attribute matches (OR semantics)
- **`has_none_of_identity_attributes`**: the principal matches if **none** of the listed identity attributes match (negation)

(policy-identity-attribute-tag-matches)=

## Identity-attribute tag matches

Match a principal's identity attribute against a {term}`governed tag` on the securable (mask policies only):

- **`has_identity_attribute_tag_matches`**: each `{attribute_key: tag_key}` entry renders as `has_identity_attribute_tag_match('attribute_key', 'tag_key')`; the `tag_key` must be a governed tag key; AND semantics; no wildcard
- **`has_any_of_identity_attribute_tag_matches`**: OR semantics
- **`has_none_of_identity_attribute_tag_matches`**: negation; AND-joined

(policy-combined-when-clause)=

## How predicates combine

All tag, context-attribute, and identity-attribute predicates combine into one `WHEN` clause as AND-of-groups:

- All `has_*` entries are AND-joined
- All `has_any_of_*` entries are OR-joined
- All `has_none_of_*` entries are negated and AND-joined
- The three groups combine with AND

For example:

```yaml
has_tags:
  domain: customer
has_any_of_tags:
  pii: email
  class.email: '*'
has_none_of_tags:
  archived: '*'
```

Renders as: `has_tag_value('domain', 'customer') AND (has_tag_value('pii', 'email') OR has_tag('class.email')) AND NOT has_tag('archived')`.

## Predicate availability

```{list-table}
:header-rows: 1
:widths: 30 15 15 15 15

* - Predicate
  - Mask
  - Filter
  - Grant
  - Wildcard
* - `has_tags`
  - Yes
  - Yes
  - Yes
  - Yes (`'*'`)
* - `has_any_of_tags`
  - Yes
  - Yes
  - Yes
  - Yes (`'*'`)
* - `has_none_of_tags`
  - Yes
  - Yes
  - No
  - Yes (`'*'`)
* - `has_context_attributes`
  - Yes
  - Yes
  - No
  - Yes (`'*'`)
* - `has_any_of_context_attributes`
  - Yes
  - Yes
  - No
  - Yes (`'*'`)
* - `has_none_of_context_attributes`
  - Yes
  - Yes
  - No
  - Yes (`'*'`)
* - `has_identity_attributes`
  - Yes
  - No
  - No
  - No
* - `has_any_of_identity_attributes`
  - Yes
  - No
  - No
  - No
* - `has_none_of_identity_attributes`
  - Yes
  - No
  - No
  - No
* - `has_identity_attribute_tag_matches`
  - Yes
  - No
  - No
  - No
* - `has_any_of_identity_attribute_tag_matches`
  - Yes
  - No
  - No
  - No
* - `has_none_of_identity_attribute_tag_matches`
  - Yes
  - No
  - No
  - No
```
