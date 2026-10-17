(glossary)=

# Glossary

```{glossary}
definition
  A reusable, environment-agnostic template declared under `definitions:` (a catalog, schema,
  table, volume, function, policy, or group). A definition is never deployed by itself; it takes
  effect only when a {term}`resource` references it. See {ref}`definitions-and-resources`.

resource
  A concrete, deployable object declared under `resources:`, such as a catalog, group, governed
  tag, or Discovery domain. Resources often `$ref` a {term}`definition` and override what differs.

definition ID
  The key of an entry under `definitions:` (for example `operations|sales|orders`). It is the
  stable identity that `$ref: $defs/<type>/<key>` points at.

securable
  A Unity Catalog object that privileges, tags, and policies attach to: a catalog, schema, table,
  volume, function, or column.

feature scope
  The value of a `--<feature>-scopes` flag. It names which resources a mutating feature applies
  to: empty disables the feature, `*` covers everything, and otherwise it is a comma-separated
  list of patterns. See {ref}`feature-scopes`.

governed tag
  An account-level tag policy that fixes a tag key's allowed values and who may assign it. See
  {ref}`governed-tags`.

principal
  A user, group, or service principal referenced as an owner, policy target, tag assigner, group
  member, or domain owner. See {ref}`principals`.
```
