(groups)=

# Groups

Account groups and their membership are deployed under `resources: groups:`. They are account-level singletons, so a group resource is what actually gets reconciled. The dictionary key is used as the group's display name if `name` is not provided.

## Fields

**`name`**: The group's display name.

**`id`**: (optional) The group's account-level internal id. When set, the engine matches the group by `id` instead of by name, which enables **renaming**: keep the `id` fixed and change `name`, and the engine updates the group's display name rather than treating it as a new group. Omit it for groups you never intend to rename.

**`members`**: (optional) A list of principals (users, groups, or service principals by display name) that must belong to the group. **Authoritative only when supplied**: omit it (or set it to `null`) to leave the group's current membership untouched. A supplied list, **including an empty list `[]`**, is enforced: `[]` removes all members, and a populated list reconciles the group to exactly those principals.

**`assumers`**: (optional) A list of principals granted the **assumer** role (`roles/group.assumer`) on the group's account [access-control rule set](https://docs.databricks.com/aws/en/security/auth/rbac). This role lets non-account-admins manage the group's role assignments. Same authoritative-only-when-supplied semantics as `members`: omit it to leave assumers alone, `[]` removes all.

**`expiry_date`**: (optional) An ISO date (`YYYY-MM-DD`). When a deployment runs on or after this date, all of the group's members and assumers are removed (the group itself is not deleted). Takes effect only under `--group-modification-scopes`. The date is computed in the configured `timezone` setting (UTC by default).

(groups-behaviour)=

## Behaviour

Group management is governed by three independent scopes, all off by default. With none of
them set, configured groups are ignored.

Creation (`--group-creation-scopes`)
: Creates an in-scope configured group that doesn't exist yet, **empty**. The engine
  automatically receives the `MANAGER` role on groups it creates. Members and assumers are
  applied by the modification scope, so to fully provision a new group in one run, include it in
  both scopes.

Members and assumers (`--group-modification-scopes`)
: Reconciles the members and assumers of in-scope groups, both existing groups and groups
  created in the same run. For each field supplied in config, configured principals that are
  missing are added and present principals absent from config are removed. An omitted field is
  left alone. Member reconciliation requires the engine to hold the `MANAGER` role on each
  managed group. Under this scope, an in-scope configured group that doesn't exist is a fatal
  error unless the creation scope also covers it.

Expiry (`--group-modification-scopes`)
: When a group's `expiry_date` has been reached, the group is treated as having no members and
  no assumers, so all of them are removed. The group itself is kept. Without the modification
  scope, `expiry_date` has no effect.

Renaming (`--group-modification-scopes`)
: When a group sets an `id` and its `name` differs from the current display name, the engine
  renames the group instead of creating a new one. Update your config references (owners,
  governed tag assigners, policy and grant principals) to the **new** name: a stale reference to
  the old name is a fatal error. Grants, policies, assigners, and memberships already deployed
  under the old name are mapped to the new name automatically, so a rename run causes no
  spurious changes. A configured `id` that matches no account group is a fatal error, as is
  renaming a group to a display name another group already uses.

Deletion (`--group-deletion-scopes`)
: Makes config authoritative over which groups exist: a matching Databricks-managed group absent
  from `resources.groups` is deleted. External (IdP-provisioned) groups and the account system
  groups (`account users`, `account admins`) are never deleted. Requires `--group-creation-scopes`
  to be active and at least one group declared under `resources.groups`, and asks for
  confirmation unless `--force` is set.

### Restrictions

- **Externally managed groups**, provisioned from an IdP (they carry an `external_id`), may be
  declared only **without** `members`, since the IdP owns their membership; supplying `members`
  is a fatal error. They are never renamed. Their `assumers` can still be managed.
- **Account system groups** (`account users`, `account admins`) cannot be declared in
  `resources.groups`; declaring one is a config error.
- **Workspace SCIM mode.** Group scopes need account-level access, so they can't be combined
  with the deprecated `--use-workspace-scim` flag (see {ref}`deprecations`).
- **Ordering.** Groups are reconciled first, before governed tags, so groups referenced as
  principals exist (and renames are reflected) before anything uses them.

## Example

```{code-block} yaml
:caption: resources/groups/data_engineers.yaml

resources:
  groups:
    data_engineers:
      name: data_engineers
      # id: "1234567890123456"   # set to rename: keep id, change name above
      # expiry_date: 2026-12-31  # on or after this date, all members and assumers are removed
      members:                    # omit to leave membership unmanaged; [] removes all
        - alice@example.com
        - bob@example.com
        - platform_admins         # groups can be members of groups
        - etl-service-principal   # service principals by display name
      assumers:                   # principals allowed to manage this group's role assignments
        - group_admins
```

Groups can also be captured as reusable `definitions: groups:` templates and pulled in with
`$ref: $defs/groups/<key>`, which is useful with {ref}`template-variables` for per-environment
group families.
