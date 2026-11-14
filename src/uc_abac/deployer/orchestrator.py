from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from databricks.sdk import WorkspaceClient

from uc_abac.configs import (
    ResourcesConfig,
)
from uc_abac.errors import ExecutionBatchError, OrchestratorError
from uc_abac.fetcher import ActualState, fetch_actual_state
from uc_abac.helpers import (
    UnityCatalogHelper,
    WorkspaceHelper,
)
from uc_abac.logger import ChangeLogger
from uc_abac.resources.domains import (
    DomainDiff,
    compile_desired_domains,
    compute_domain_diff,
    execute_domain_diff,
)
from uc_abac.resources.governed_tags import (
    GovernedTag,
    GovernedTagDiff,
    compile_desired_governed_tags,
    compute_governed_tag_diff,
    execute_governed_tag_diff,
)
from uc_abac.resources.policies import (
    Policy,
    PolicyDiff,
    compile_desired_policies,
    compute_policy_diff,
    execute_policy_diff,
)
from uc_abac.resources.principals import (
    GroupDiff,
    PrincipalResolver,
    compile_desired_groups,
    compute_group_diff,
    execute_group_diff,
    groups_pending_creation,
)
from uc_abac.resources.privileges import (
    PrivilegeDiff,
    SecurablePrivilege,
    compile_desired_privileges,
    compute_privilege_diff,
    execute_privilege_diff,
)
from uc_abac.resources.securables import (
    SecurableAttributes,
    SecurableDiff,
    SecurableKey,
    compile_desired_attributes,
    compile_desired_securables,
    compute_securable_diff,
    execute_securable_diff,
    targets_nonexistent_securable,
)
from uc_abac.resources.tags import (
    SecurableTag,
    TagDiff,
    compile_desired_tags,
    compute_tag_diff,
    execute_tag_diff,
    filter_retained_removals,
    filter_unmanaged_removals,
    project_tag_state,
)
from uc_abac.types import SecurableType
from uc_abac.utils import (
    RunContext,
    Scope,
    parse_flat_scope,
    parse_hierarchical_scope,
    parse_namespace_filter,
    run_date_for_timezone,
    scope_from_namespace_tokens,
)
from uc_abac.validator import load_config

_logger = logging.getLogger("uc_abac")


@dataclass(frozen=True)
class OrchestratorDiffsResult:
    """Computed diffs from one ``orchestrator.run()`` invocation, one per domain.

    Ordered as the domains are orchestrated — the groups domain runs first.
    """

    group_diff: GroupDiff
    securable_diff: SecurableDiff
    governed_tag_diff: GovernedTagDiff
    domain_diff: DomainDiff
    tag_diff: TagDiff
    policy_diff: PolicyDiff
    privilege_diff: PrivilegeDiff


def _filter_securable_attributes(
    attrs: set[SecurableAttributes],
    scope: Scope,
) -> set[SecurableAttributes]:
    """Drop non-function attributes whose namespace isn't in scope.

    FUNCTION attributes always flow through (functions are engine-managed
    independently of the securable-modification scope). When ``scope`` is empty
    (inert), this collapses to "function attributes only" — which is the
    behaviour when securable management is off.
    """
    return {
        a
        for a in attrs
        if a.securable_type == SecurableType.FUNCTION or scope.matches(a.full_name)
    }


def _collect_configured_namespaces(config: ResourcesConfig) -> set[str]:
    """Collect every namespace token a filter flag may reference.

    That is each configured catalog name plus every configured
    ``catalog.schema`` full name — the valid tokens ``parse_namespace_filter``
    validates entries against.
    """
    namespaces: set[str] = set()
    for catalog in config.catalogs.values():
        namespaces.add(catalog.full_name)
        for schema in catalog.schemas or []:
            namespaces.add(schema.full_name)
    return namespaces


def _collect_configured_full_names(config: ResourcesConfig) -> set[str]:
    """Every configured securable full name at every level.

    Unlike ``_collect_configured_namespaces`` (catalog/schema only, kept narrow so
    the legacy ``parse_namespace_filter`` validation is unchanged), this reaches
    tables, columns, volumes, and functions — the universe a new-style
    hierarchical scope is checked against for zero-match warnings.
    """
    names: set[str] = set()
    for catalog in config.catalogs.values():
        names.add(catalog.full_name)
        for schema in catalog.schemas or []:
            names.add(schema.full_name)
            for table in schema.tables or []:
                names.add(table.full_name)
                for column in table.columns or []:
                    names.add(column.full_name)
            for volume in schema.volumes or []:
                names.add(volume.full_name)
            for function in schema.functions or []:
                names.add(function.full_name)
    return names


def _build_hierarchical_scope(
    new_spec: str | None,
    *,
    legacy_enabled: bool,
    legacy_namespaces: str,
    configured_namespaces: set[str],
) -> Scope:
    """Resolve one securable-domain feature to a ``Scope``.

    A new-style spec (non-``None``) wins and is parsed leniently. Otherwise the
    legacy enable + ``*_for_namespaces`` pair is honoured: when enabled, the
    namespace string is validated strictly via ``parse_namespace_filter`` and
    wrapped as a hierarchical scope byte-equivalent to the old
    ``in_namespace_scope``; when disabled, an empty (inert) scope.
    """
    if new_spec is not None:
        return parse_hierarchical_scope(new_spec)
    if legacy_enabled:
        tokens = parse_namespace_filter(legacy_namespaces, configured_namespaces)
        return scope_from_namespace_tokens(tokens)
    return Scope()


def _build_flat_scope(new_spec: str | None, *, legacy_enabled: bool) -> Scope:
    """Resolve one flat-domain feature (groups, governed tags) to a ``Scope``.

    A new-style spec wins; otherwise the legacy enable bool maps to match-all
    when set, or an empty (inert) scope when unset.
    """
    if new_spec is not None:
        return parse_flat_scope(new_spec)
    return parse_flat_scope("*") if legacy_enabled else Scope()


def _warn_unmatched_scopes(
    named_scopes: list[tuple[str, str | None, Scope]],
    universe: set[str],
) -> None:
    """Warn (never fail) about new-style scope entries that match nothing.

    Only new-style specs (``new_spec is not None``) are checked — legacy flags
    retain their own strict validation. Each unmatched entry is a likely typo.
    """
    for flag, new_spec, scope in named_scopes:
        if new_spec is None:
            continue
        unmatched = scope.unmatched_entries(universe)
        if unmatched:
            _logger.warning(
                "%s: scope entr%s %s matched no configured resource — "
                "possible typo (this feature will govern nothing for %s).",
                flag,
                "y" if len(unmatched) == 1 else "ies",
                ", ".join(repr(u) for u in unmatched),
                "it" if len(unmatched) == 1 else "them",
            )


def _scope_domain_changes(
    diff: DomainDiff,
    creation_scope: Scope,
    modification_scope: Scope,
) -> DomainDiff:
    """Gate domain creates and updates independently while preserving scoped deletions.

    The creation scope gates ``to_create`` and the modification scope gates
    ``to_update`` (with its ``old_values`` / ``update_masks``), so the two act as
    independent gates — mirroring the group creation/modification scopes. Deletion
    authority is evaluated against the full declared domain set before this helper
    runs, so a declared domain outside both scopes remains protected from deletion
    while its metadata stays untouched.
    """
    return DomainDiff(
        to_create={
            domain
            for domain in diff.to_create
            if creation_scope.matches(domain.tag_key)
        },
        to_update={
            domain
            for domain in diff.to_update
            if modification_scope.matches(domain.tag_key)
        },
        to_delete=set(diff.to_delete),
        old_values={
            tag_key: domain
            for tag_key, domain in diff.old_values.items()
            if modification_scope.matches(tag_key)
        },
        update_masks={
            tag_key: mask
            for tag_key, mask in diff.update_masks.items()
            if modification_scope.matches(tag_key)
        },
    )


def _warn_deprecated_flags(
    use_workspace_scim: bool,
    skip_users_fetch: bool,
    ref_override_strategy: str,
) -> None:
    """Log a deprecation warning for each legacy flag that is still in effect.

    ``use_workspace_scim`` / ``skip_users_fetch`` predate the current account path
    (Workspace Identity V2 reads listing every account principal). ``ref_override_strategy``
    only warns for the non-default ``replace`` value — the deprecated behaviour — since
    the default ``merge`` is the go-forward mode and is indistinguishable at this layer
    from omitting the flag. All remain functional for now but are slated for removal, so
    a run that uses one is told to omit it."""
    if use_workspace_scim:
        _logger.warning(
            "--use-workspace-scim is deprecated and will be removed in a future "
            "release; omit it. The default account path now lists all account "
            "principals, so the workspace-SCIM mode is no longer needed."
        )
    if skip_users_fetch:
        _logger.warning(
            "--skip-users-fetch is deprecated and will be removed in a future "
            "release; omit it."
        )
    if ref_override_strategy != "merge":
        _logger.warning(
            "--ref-override-strategy is deprecated and will be removed in a future "
            "release; omit it. The 'replace' strategy in particular is going away — "
            "migrate configs to rely on the default 'merge' behaviour."
        )


def _build_run_context(
    config: ResourcesConfig,
    *,
    system_catalog: str,
    information_schema: str,
    per_catalog_information_schema: bool,
    timezone: str,
    dry_run: bool,
    use_workspace_scim: bool,
    skip_users_fetch: bool,
    enable_tag_management: bool,
    enable_taggable_management: bool,
    enable_taggable_creation: bool,
    enable_privilege_management: bool,
    enable_governed_tag_deletion: bool,
    enable_policy_deletion: bool,
    enable_group_creation: bool,
    enable_group_management: bool,
    enable_group_deletion: bool,
    ignore_unresolvable_principals: str,
    manage_tags_for_namespaces: str,
    manage_privileges_for_namespaces: str,
    manage_taggables_for_namespaces: str,
    create_taggables_for_namespaces: str,
    delete_policies_for_namespaces: str,
    tag_management_scopes: str | None,
    tag_assignment_scopes: str | None,
    privilege_management_scopes: str | None,
    securable_modification_scopes: str | None,
    securable_creation_scopes: str | None,
    policy_deletion_scopes: str | None,
    group_creation_scopes: str | None,
    group_modification_scopes: str | None,
    group_deletion_scopes: str | None,
    governed_tag_deletion_scopes: str | None,
    domain_creation_scopes: str | None,
    domain_modification_scopes: str | None,
    domain_deletion_scopes: str | None,
    retain_tag_prefixes: str,
    warn_on_nonexistent_securables: bool,
    ref_override_strategy: str,
    force: bool,
    max_parallel_changes: int,
) -> RunContext:
    """Resolve raw ``run()`` keyword arguments into a frozen :class:`RunContext`.

    Owns the whole settings-resolution step: deprecation warnings, resolving every
    feature to a single ``Scope`` (a new-style ``*_scopes`` spec wins; otherwise the
    deprecated ``enable_* `` + ``*_for_namespaces`` pair is honoured identically),
    the unmatched-scope typo warnings, the fatal group/scim/skip-users and
    group-deletion validations, the ``run_date`` (computed once in the configured
    timezone), the retain-prefix / ignore-unresolvable frozensets, and
    ``manage_domain_owners`` (which needs ``config.domains`` owner declarations).

    The run date is computed here so both compilers (groups and grant policies)
    evaluate every ``expiry_date`` against the same date, even across a midnight
    boundary.
    """
    _warn_deprecated_flags(use_workspace_scim, skip_users_fetch, ref_override_strategy)

    run_date = run_date_for_timezone(timezone)
    configured_namespaces = _collect_configured_namespaces(config)
    configured_full_names = _collect_configured_full_names(config)

    tag_management_scope = _build_hierarchical_scope(
        tag_management_scopes,
        legacy_enabled=enable_tag_management,
        legacy_namespaces=manage_tags_for_namespaces,
        configured_namespaces=configured_namespaces,
    )
    # Raw assignment scope for warning; effective scope is the union (management subsumes).
    raw_tag_assignment_scope = parse_hierarchical_scope(tag_assignment_scopes or "")
    # Store the EFFECTIVE scope in RunContext: assignment scope unioned with management
    # scope. When both are set, management scope subsumes assignment scope, so all
    # management-scoped securables also get assignment behavior.
    effective_tag_assignment_scope = raw_tag_assignment_scope.union(
        tag_management_scope
    )
    privilege_management_scope = _build_hierarchical_scope(
        privilege_management_scopes,
        legacy_enabled=enable_privilege_management,
        legacy_namespaces=manage_privileges_for_namespaces,
        configured_namespaces=configured_namespaces,
    )
    securable_modification_scope = _build_hierarchical_scope(
        securable_modification_scopes,
        legacy_enabled=enable_taggable_management,
        legacy_namespaces=manage_taggables_for_namespaces,
        configured_namespaces=configured_namespaces,
    )
    securable_creation_scope = _build_hierarchical_scope(
        securable_creation_scopes,
        legacy_enabled=enable_taggable_creation,
        legacy_namespaces=create_taggables_for_namespaces,
        configured_namespaces=configured_namespaces,
    )
    policy_deletion_scope = _build_hierarchical_scope(
        policy_deletion_scopes,
        legacy_enabled=enable_policy_deletion,
        legacy_namespaces=delete_policies_for_namespaces,
        configured_namespaces=configured_namespaces,
    )
    group_creation_scope = _build_flat_scope(
        group_creation_scopes, legacy_enabled=enable_group_creation
    )
    group_modification_scope = _build_flat_scope(
        group_modification_scopes, legacy_enabled=enable_group_management
    )
    group_deletion_scope = _build_flat_scope(
        group_deletion_scopes, legacy_enabled=enable_group_deletion
    )
    governed_tag_deletion_scope = _build_flat_scope(
        governed_tag_deletion_scopes, legacy_enabled=enable_governed_tag_deletion
    )
    domain_creation_scope = _build_flat_scope(
        domain_creation_scopes, legacy_enabled=False
    )
    domain_modification_scope = _build_flat_scope(
        domain_modification_scopes, legacy_enabled=False
    )
    domain_deletion_scope = _build_flat_scope(
        domain_deletion_scopes, legacy_enabled=False
    )

    # Fetch and compare domain owners only when the domain workflow runs and any
    # declared domain sets owners.
    domain_workflow_active = (
        domain_creation_scope.is_active()
        or domain_modification_scope.is_active()
        or domain_deletion_scope.is_active()
    )
    manage_domain_owners = domain_workflow_active and any(
        domain.business_owners is not None or domain.technical_owners is not None
        for domain in (config.domains or {}).values()
    )

    # Warn (never fail) about new-style hierarchical scope entries that match no
    # configured securable — a likely typo that would silently govern nothing.
    _warn_unmatched_scopes(
        [
            ("--tag-management-scopes", tag_management_scopes, tag_management_scope),
            (
                "--tag-assignment-scopes",
                tag_assignment_scopes,
                raw_tag_assignment_scope,
            ),
            (
                "--privilege-management-scopes",
                privilege_management_scopes,
                privilege_management_scope,
            ),
            (
                "--securable-modification-scopes",
                securable_modification_scopes,
                securable_modification_scope,
            ),
            (
                "--securable-creation-scopes",
                securable_creation_scopes,
                securable_creation_scope,
            ),
            ("--policy-deletion-scopes", policy_deletion_scopes, policy_deletion_scope),
        ],
        configured_full_names,
    )

    # Group creation/management operate at the account level via the account SCIM
    # proxy. The workspace SCIM API surfaces only workspace-level groups and cannot
    # create or manage account groups, so enabling a group scope under
    # --use-workspace-scim is unsupported. (Configuring groups without any group
    # scope is inert and compatible with --use-workspace-scim.)
    group_domain_active = (
        group_creation_scope.is_active() or group_modification_scope.is_active()
    )
    if config.groups and group_domain_active and use_workspace_scim:
        raise OrchestratorError(
            "Group creation/management requires the account SCIM proxy, but "
            "--use-workspace-scim was set. Remove --use-workspace-scim to create or "
            "manage the groups declared in config."
        )
    # Resolving user members of a managed group requires the account users list, so
    # group modification cannot run alongside --skip-users-fetch.
    if config.groups and group_domain_active and skip_users_fetch:
        raise OrchestratorError(
            "Group creation/management requires the account users list to resolve "
            "user members, but --skip-users-fetch was set. Remove --skip-users-fetch "
            "to create or manage the groups declared in config."
        )
    # Group deletion makes config authoritative over group existence — it is only
    # usable alongside group creation, and never against an empty config (a
    # destructive account-wide sweep with no declared groups is disallowed outright).
    if group_deletion_scope.is_active() and not config.groups:
        raise OrchestratorError(
            "Group deletion is enabled but no groups are declared under "
            "resources.groups. Declare the groups config should own, or disable "
            "group deletion."
        )
    if group_deletion_scope.is_active() and not group_creation_scope.is_active():
        raise OrchestratorError(
            "Group deletion requires group creation to also be active (config must "
            "be authoritative over group existence). Enable group creation, or "
            "disable group deletion."
        )

    # Tag-key prefixes whose tags are never removed (only added/updated). Empty
    # string ⇒ no retention. Defaults to "class." to protect auto-classification.
    retain_prefixes = frozenset(
        p.strip() for p in retain_tag_prefixes.split(",") if p.strip()
    )
    # Actual-state (UC-side) identifiers whose resolution-failure warning is
    # suppressed across the privileges, securables (owner), and governed-tags
    # (assigners) domains. Matched by identifier only; resolvable principals are
    # unaffected. Empty by default ⇒ all unresolvable-principal warnings emitted.
    ignore_unresolvable = frozenset(
        p.strip() for p in ignore_unresolvable_principals.split(",") if p.strip()
    )

    return RunContext(
        tag_management_scope=tag_management_scope,
        tag_assignment_scope=effective_tag_assignment_scope,
        privilege_management_scope=privilege_management_scope,
        securable_modification_scope=securable_modification_scope,
        securable_creation_scope=securable_creation_scope,
        policy_deletion_scope=policy_deletion_scope,
        group_creation_scope=group_creation_scope,
        group_modification_scope=group_modification_scope,
        group_deletion_scope=group_deletion_scope,
        governed_tag_deletion_scope=governed_tag_deletion_scope,
        domain_creation_scope=domain_creation_scope,
        domain_modification_scope=domain_modification_scope,
        domain_deletion_scope=domain_deletion_scope,
        run_date=run_date,
        retain_prefixes=retain_prefixes,
        ignore_unresolvable=ignore_unresolvable,
        system_catalog=system_catalog,
        information_schema=information_schema,
        per_catalog_information_schema=per_catalog_information_schema,
        use_workspace_scim=use_workspace_scim,
        skip_users_fetch=skip_users_fetch,
        dry_run=dry_run,
        force=force,
        max_parallel_changes=max_parallel_changes,
        manage_domain_owners=manage_domain_owners,
        warn_on_nonexistent_securables=warn_on_nonexistent_securables,
    )


def _compute_tag_workflow(
    config: ResourcesConfig,
    governed_tags: set[GovernedTag],
    actual_tags: set[SecurableTag],
    settings: RunContext,
    retain_prefixes: frozenset[str],
    change_logger: ChangeLogger,
) -> tuple[TagDiff, set[SecurableTag]]:
    """Compute the tag diff and the tag state used for grant-policy matching.

    The effective assignment scope (the union of ``--tag-assignment-scopes`` and
    ``--tag-management-scopes``, since management subsumes assignment) drives the
    diff, so in-scope securables get tags added and values updated. Removals are
    then kept only for securables in the management scope, and never for tags
    matching a retained prefix.

    Grant policies are matched against the projected post-run state (actual tags,
    minus removals, plus adds and updates) — what UC will hold once the diff is
    applied. Tags left in place (retained prefixes, assignment-only securables) still
    count, and tags about to be added count this run. Out-of-scope securables pass
    through unchanged because the diff never touches them. With both scopes empty
    the engine applies no tags, so grants match against the on-disk state.
    """
    if not settings.enable_tag_assignment:
        return TagDiff(), actual_tags

    desired_tags = compile_desired_tags(config, governed_tags, change_logger)
    in_scope_desired_tags = {
        t
        for t in desired_tags
        if settings.tag_assignment_scope.matches(t.securable_full_name)
    }
    in_scope_actual_tags = {
        t
        for t in actual_tags
        if settings.tag_assignment_scope.matches(t.securable_full_name)
    }
    tag_diff = compute_tag_diff(in_scope_desired_tags, in_scope_actual_tags)
    tag_diff, retained_tags = filter_retained_removals(tag_diff, retain_prefixes)
    if retained_tags:
        _logger.info(
            f"  Retaining {len(retained_tags)} unconfigured tag(s) matching "
            f"prefix(es) {sorted(retain_prefixes)} — these will not be removed"
        )
    tag_diff, kept_by_scope = filter_unmanaged_removals(
        tag_diff, settings.tag_management_scope
    )
    if kept_by_scope:
        _logger.info(
            f"  Keeping {len(kept_by_scope)} tag(s) on securables covered only by "
            f"--tag-assignment-scopes — these will not be removed"
        )
    return tag_diff, project_tag_state(actual_tags, tag_diff)


def _filter_nonexistent_securable_diff(diff: SecurableDiff) -> SecurableDiff:
    """Remove securable operations whose target is known not to exist.

    A missing parent suppresses operations for its descendants too. Functions are
    normally engine-created, but a function below a missing catalog or schema cannot
    be created and must therefore be removed with the other dependent operations.
    """
    nonexistent = diff.nonexistent_securables
    return SecurableDiff(
        attributes_to_update=[
            update
            for update in diff.attributes_to_update
            if not targets_nonexistent_securable(
                update.securable_type, update.full_name, nonexistent
            )
        ],
        securables_to_create=[
            securable
            for securable in diff.securables_to_create
            if not targets_nonexistent_securable(
                securable.securable_type, securable.full_name, nonexistent
            )
        ],
        securables_to_replace=[
            securable
            for securable in diff.securables_to_replace
            if not targets_nonexistent_securable(
                securable.securable_type, securable.full_name, nonexistent
            )
        ],
        old_securables={
            full_name: securable
            for full_name, securable in diff.old_securables.items()
            if not targets_nonexistent_securable(
                securable.securable_type, securable.full_name, nonexistent
            )
        },
        nonexistent_securables=nonexistent,
    )


def _filter_nonexistent_tags(
    tags: set[SecurableTag],
    nonexistent: frozenset[SecurableKey],
) -> set[SecurableTag]:
    """Exclude tag state whose target is missing or below a missing parent."""
    return {
        tag
        for tag in tags
        if not targets_nonexistent_securable(
            tag.securable_type,
            tag.securable_full_name,
            nonexistent,
        )
    }


def _filter_nonexistent_tag_diff(
    diff: TagDiff,
    nonexistent: frozenset[SecurableKey],
) -> TagDiff:
    """Remove tag operations and prior values for missing targets."""

    return TagDiff(
        to_add=_filter_nonexistent_tags(diff.to_add, nonexistent),
        to_update=_filter_nonexistent_tags(diff.to_update, nonexistent),
        to_remove=_filter_nonexistent_tags(diff.to_remove, nonexistent),
        old_values={
            key: value
            for key, value in diff.old_values.items()
            if not targets_nonexistent_securable(key[0], key[1], nonexistent)
        },
    )


def _filter_nonexistent_policy_diff(
    diff: PolicyDiff,
    nonexistent: frozenset[SecurableKey],
) -> PolicyDiff:
    """Remove policy operations and prior policies for missing targets."""

    def keep_policy(policy: Policy) -> bool:
        return not targets_nonexistent_securable(
            policy.securable_type, policy.securable_full_name, nonexistent
        )

    return PolicyDiff(
        to_create={policy for policy in diff.to_create if keep_policy(policy)},
        to_replace={policy for policy in diff.to_replace if keep_policy(policy)},
        to_delete={policy for policy in diff.to_delete if keep_policy(policy)},
        old_policies={
            key: policy
            for key, policy in diff.old_policies.items()
            if not targets_nonexistent_securable(key[0], key[1], nonexistent)
        },
    )


def _filter_nonexistent_privilege_diff(
    diff: PrivilegeDiff,
    nonexistent: frozenset[SecurableKey],
) -> PrivilegeDiff:
    """Remove privilege grants and revocations for missing targets."""

    def keep_privilege(privilege: SecurablePrivilege) -> bool:
        return not targets_nonexistent_securable(
            privilege.securable_type,
            privilege.securable_full_name,
            nonexistent,
        )

    return PrivilegeDiff(
        to_grant={item for item in diff.to_grant if keep_privilege(item)},
        to_revoke={item for item in diff.to_revoke if keep_privilege(item)},
    )


def _filter_nonexistent_securable_changes(
    securable_diff: SecurableDiff,
    tag_diff: TagDiff,
    policy_diff: PolicyDiff,
    privilege_diff: PrivilegeDiff,
) -> tuple[SecurableDiff, TagDiff, PolicyDiff, PrivilegeDiff]:
    """Prune every domain's operations after all diffs have been computed.

    Keeping this as a post-diff step ensures all downstream domains use the same
    missing-object decision, including when an individual differ is replaced by an
    integration or test double.
    """
    nonexistent = securable_diff.nonexistent_securables
    return (
        _filter_nonexistent_securable_diff(securable_diff),
        _filter_nonexistent_tag_diff(tag_diff, nonexistent),
        _filter_nonexistent_policy_diff(policy_diff, nonexistent),
        _filter_nonexistent_privilege_diff(privilege_diff, nonexistent),
    )


def _execute_changes(
    config: ResourcesConfig,
    actual_state: ActualState,
    uc_helper: UnityCatalogHelper,
    ws_helper: WorkspaceHelper,
    settings: RunContext,
    change_logger: ChangeLogger,
) -> OrchestratorDiffsResult:
    """Compile desired state, diff it against ``actual_state``, and execute changes.

    Compilation stays inline here, in the same order as before: the governed-tag
    diff is computed first so domains are compiled against the governed-tag union
    *minus* tags selected for deletion, and privileges are matched against the tag
    state that will be in effect (desired in-scope ∪ actual out-of-scope, or on-disk
    actual tags when tag management is off). The shared ``PrincipalResolver`` is
    built from the (cache-populated) ``ws_helper``; groups slated for creation and
    rename are seeded into that cache before downstream domains resolve principals.

    Returns the per-domain diffs. The caller (``run``) owns the error-summary /
    ``ExecutionBatchError`` gating after this returns.
    """
    run_date = settings.run_date
    ignore_unresolvable = settings.ignore_unresolvable
    retain_prefixes = settings.retain_prefixes
    dry_run = settings.dry_run
    force = settings.force
    max_parallel_changes = settings.max_parallel_changes

    actual_securables = set(actual_state.securables)
    actual_attributes = set(actual_state.attributes)
    actual_policies = set(actual_state.policies)
    actual_governed_tags = set(actual_state.governed_tags)
    actual_tags = set(actual_state.tags)
    actual_privileges = set(actual_state.privileges)
    actual_domains = set(actual_state.domains)
    actual_groups = set(actual_state.groups)
    all_account_groups = set(actual_state.all_account_groups)

    # Shared resolver over the already-populated ws_helper cache.
    resolver = PrincipalResolver(ws_helper)

    # Seed the display names of groups this run will create into the principal cache
    # *before* the diff, so a configured group's members that are themselves created
    # this run resolve during member resolution (they don't exist in the account yet).
    desired_groups = compile_desired_groups(config, run_date=run_date)
    if settings.group_domain_active:
        ws_helper.register_pending_groups(
            groups_pending_creation(
                desired_groups,
                actual_groups,
                settings.enable_group_creation,
                settings.group_creation_scope,
            )
        )

    # Group workflow (the first domain — runs before governed tags so that any groups
    # referenced as policy/grant principals exist first). Inert unless a group flag is
    # set.
    group_diff = (
        compute_group_diff(
            desired_groups,
            actual_groups,
            resolver,
            change_logger,
            enable_group_creation=settings.enable_group_creation,
            enable_group_modification=settings.enable_group_modification,
            enable_group_deletion=settings.enable_group_deletion,
            ignore_unresolvable=ignore_unresolvable,
            all_account_groups=all_account_groups,
            creation_scope=settings.group_creation_scope,
            modification_scope=settings.group_modification_scope,
            deletion_scope=settings.group_deletion_scope,
        )
        if settings.group_domain_active
        else GroupDiff()
    )
    # Renames are reflected in the principal cache before downstream domains resolve:
    # the new display name becomes resolvable and the old one becomes unknown (even in
    # dry-run, where the SCIM PATCH itself is skipped).
    ws_helper.register_pending_renames(group_diff.groups_to_rename)

    # Governed tags workflow (account-level tag policies — must run before
    # catalog-scoped tag assignments, so new tag keys exist before SET TAGS).
    desired_governed_tags = compile_desired_governed_tags(config)
    governed_tag_diff = compute_governed_tag_diff(
        desired_governed_tags,
        actual_governed_tags,
        resolver,
        change_logger,
        enable_deletion=settings.enable_governed_tag_deletion,
        ignore_unresolvable=ignore_unresolvable,
        deletion_scope=settings.governed_tag_deletion_scope,
    )
    # Union of declared governed tags (desired from config + actual on UC). The names
    # gate policy/privilege tag references; the full objects validate securable tag
    # values against allowed_values. Domains are compiled against the union minus the
    # tags selected for deletion this run.
    governed_tags_by_name = {tag.name: tag for tag in actual_governed_tags}
    governed_tags_by_name.update({tag.name: tag for tag in desired_governed_tags})
    governed_tags = set(governed_tags_by_name.values())
    governed_tag_names = {t.name for t in governed_tags}
    deleted_governed_tag_names = {tag.name for tag in governed_tag_diff.to_delete}
    domain_source_governed_tags = {
        tag for tag in governed_tags if tag.name not in deleted_governed_tag_names
    }
    desired_domains = (
        compile_desired_domains(config, domain_source_governed_tags)
        if settings.domain_workflow_active
        else set()
    )
    computed_domain_diff = (
        compute_domain_diff(
            desired_domains,
            actual_domains,
            change_logger,
            resolver,
            deletion_scope=settings.domain_deletion_scope,
            ignore_unresolvable=ignore_unresolvable,
        )
        if settings.domain_workflow_active
        else DomainDiff()
    )
    domain_diff = _scope_domain_changes(
        computed_domain_diff,
        settings.domain_creation_scope,
        settings.domain_modification_scope,
    )

    # Securables workflow (before tags and privileges). Drop non-function attribute
    # updates whose namespace isn't in the securable-modification scope; function
    # attributes always flow through (FUNCTION creation/replacement is always
    # engine-managed).
    desired_attributes = _filter_securable_attributes(
        compile_desired_attributes(config), settings.securable_modification_scope
    )
    in_scope_actual_attributes = _filter_securable_attributes(
        actual_attributes, settings.securable_modification_scope
    )
    securable_diff = compute_securable_diff(
        desired_attributes,
        in_scope_actual_attributes,
        compile_desired_securables(config),
        actual_securables,
        resolver,
        change_logger,
        creation_in_scope_namespaces=settings.securable_creation_scope,
        ignore_unresolvable=ignore_unresolvable,
        warn_on_nonexistent_securables=settings.warn_on_nonexistent_securables,
    )

    # Tags workflow (see _compute_tag_workflow).
    tag_diff, tags_for_privilege_matching = _compute_tag_workflow(
        config, governed_tags, actual_tags, settings, retain_prefixes, change_logger
    )

    # Policies workflow (mask/filter).
    desired_policies = compile_desired_policies(
        config,
        governed_tag_names,
        change_logger,
    )
    policy_diff = compute_policy_diff(
        desired_policies,
        actual_policies,
        resolver,
        change_logger,
        ignore_unresolvable=ignore_unresolvable,
        delete_scope=settings.policy_deletion_scope,
    )

    # Privileges workflow.
    if settings.enable_privilege_management:
        if settings.warn_on_nonexistent_securables:
            tags_for_privilege_matching = _filter_nonexistent_tags(
                tags_for_privilege_matching,
                securable_diff.nonexistent_securables,
            )
        compiled_privileges = compile_desired_privileges(
            config,
            tags_for_privilege_matching,
            governed_tag_names,
            change_logger,
            run_date=run_date,
        )
        in_scope_compiled_privileges = {
            p
            for p in compiled_privileges
            if settings.privilege_management_scope.matches(p.securable_full_name)
        }
        in_scope_actual_privileges = {
            p
            for p in actual_privileges
            if settings.privilege_management_scope.matches(p.securable_full_name)
        }
        privilege_diff = compute_privilege_diff(
            in_scope_compiled_privileges,
            in_scope_actual_privileges,
            resolver,
            change_logger,
            ignore_unresolvable=ignore_unresolvable,
        )
    else:
        privilege_diff = PrivilegeDiff()

    if settings.warn_on_nonexistent_securables:
        securable_diff, tag_diff, policy_diff, privilege_diff = (
            _filter_nonexistent_securable_changes(
                securable_diff,
                tag_diff,
                policy_diff,
                privilege_diff,
            )
        )

    # Log and execute (or dry-run) — the groups domain runs first.
    if (
        group_diff.groups_to_create
        or group_diff.members_to_add
        or group_diff.members_to_remove
        or group_diff.assumers_to_set
        or group_diff.groups_to_rename
        or group_diff.groups_to_delete
    ):
        change_logger.log_section_header("Groups")
    execute_group_diff(
        ws_helper,
        group_diff,
        change_logger,
        dry_run=dry_run,
        force=force,
        max_parallel_changes=max_parallel_changes,
    )

    if (
        governed_tag_diff.to_create
        or governed_tag_diff.to_update
        or governed_tag_diff.to_delete
    ):
        change_logger.log_section_header("Governed tags")
    execute_governed_tag_diff(
        ws_helper,
        governed_tag_diff,
        change_logger,
        dry_run=dry_run,
        force=force,
        # max_parallel_changes not currently supported for governed tags
    )

    if domain_diff.to_create or domain_diff.to_update or domain_diff.to_delete:
        change_logger.log_section_header("Domains")
    execute_domain_diff(
        ws_helper,
        domain_diff,
        change_logger,
        dry_run=dry_run,
        force=force,
    )

    if (
        securable_diff.securables_to_create
        or securable_diff.securables_to_replace
        or securable_diff.attributes_to_update
    ):
        change_logger.log_section_header("Securables")
    execute_securable_diff(
        uc_helper,
        securable_diff,
        change_logger,
        dry_run=dry_run,
        max_parallel_changes=max_parallel_changes,
        actual_securables=actual_securables,
    )

    if tag_diff.to_add or tag_diff.to_update or tag_diff.to_remove:
        change_logger.log_section_header("Tags")
    execute_tag_diff(
        uc_helper,
        tag_diff,
        change_logger,
        governed_tag_names=governed_tag_names,
        dry_run=dry_run,
        force=force,
        max_parallel_changes=max_parallel_changes,
    )

    if policy_diff.to_create or policy_diff.to_replace or policy_diff.to_delete:
        change_logger.log_section_header("Policies")
    execute_policy_diff(
        uc_helper,
        policy_diff,
        change_logger,
        dry_run=dry_run,
        force=force,
        max_parallel_changes=max_parallel_changes,
    )

    if privilege_diff.to_grant or privilege_diff.to_revoke:
        change_logger.log_section_header("Privileges")
    execute_privilege_diff(
        uc_helper,
        privilege_diff,
        change_logger,
        dry_run=dry_run,
        max_parallel_changes=max_parallel_changes,
    )

    return OrchestratorDiffsResult(
        group_diff=group_diff,
        securable_diff=securable_diff,
        governed_tag_diff=governed_tag_diff,
        domain_diff=domain_diff,
        tag_diff=tag_diff,
        policy_diff=policy_diff,
        privilege_diff=privilege_diff,
    )


def run(
    config_dir: Path,
    workspace_client: WorkspaceClient,
    warehouse_id: str,
    system_catalog: str = "system",
    information_schema: str = "system.information_schema",
    per_catalog_information_schema: bool = False,
    timezone: str = "UTC",
    dry_run: bool = False,
    use_workspace_scim: bool = False,
    skip_users_fetch: bool = False,
    enable_tag_management: bool = False,
    enable_taggable_management: bool = False,
    enable_taggable_creation: bool = False,
    enable_privilege_management: bool = False,
    enable_governed_tag_deletion: bool = False,
    enable_policy_deletion: bool = False,
    enable_group_creation: bool = False,
    enable_group_management: bool = False,
    enable_group_deletion: bool = False,
    ignore_unresolvable_principals: str = "",
    manage_tags_for_namespaces: str = "*",
    manage_privileges_for_namespaces: str = "*",
    manage_taggables_for_namespaces: str = "*",
    create_taggables_for_namespaces: str = "*",
    delete_policies_for_namespaces: str = "*",
    tag_management_scopes: str | None = None,
    tag_assignment_scopes: str | None = None,
    privilege_management_scopes: str | None = None,
    securable_modification_scopes: str | None = None,
    securable_creation_scopes: str | None = None,
    policy_deletion_scopes: str | None = None,
    group_creation_scopes: str | None = None,
    group_modification_scopes: str | None = None,
    group_deletion_scopes: str | None = None,
    governed_tag_deletion_scopes: str | None = None,
    domain_creation_scopes: str | None = None,
    domain_modification_scopes: str | None = None,
    domain_deletion_scopes: str | None = None,
    retain_tag_prefixes: str = "class.",
    warn_on_nonexistent_securables: bool = False,
    force: bool = False,
    ref_override_strategy: Literal["merge", "replace"] = "merge",
    max_parallel_changes: int = 8,
) -> OrchestratorDiffsResult:
    """Run the full governance pipeline: discover, resolve, compile, diff, apply.

    Returns the computed diffs for every domain in execution order.
    In dry-run mode, diffs are computed but no SQL is executed.

    **Feature gating.** Most mutating features resolve to a single ``Scope`` (see
    ``uc_abac.utils.Scope``) via ``_build_hierarchical_scope`` /
    ``_build_flat_scope``. A new-style ``*_scopes`` argument (non-``None``) wins
    and is parsed leniently — empty ⇒ disabled, ``"*"`` ⇒ all, otherwise a
    comma-separated pattern list (securable domains use dotted prefixes with
    downward inheritance; flat domains match names/prefixes). Otherwise the
    deprecated ``enable_*`` + ``*_for_namespaces`` pair is honoured with identical
    behaviour (strict ``parse_namespace_filter`` validation preserved). Effective
    enablement is ``scope.is_active()``: when a scope is empty the corresponding
    domain is skipped in both dry-run and real-run (no fetch, no diff, no log, no
    execute). An active ``privilege_management`` scope with both tag scopes
    (``tag_management`` and ``tag_assignment``) inactive makes the privileges
    compiler match its grant policies against the on-disk (``actual``) tag state
    instead of the projected post-run tags. A new-style scope entry that matches no applicable resource
    logs a warning (likely typo) but never fails the run.

    ``tag_assignment_scopes`` and ``tag_management_scopes`` are two scopes for
    tag governance. ``tag_assignment_scopes`` adds and updates tags but never
    removes them (assignment-only). ``tag_management_scopes`` subsumes assignment
    and additionally enables removal of unconfigured tags. When both are set,
    the effective assignment scope is their union, and tags are removed only for
    securables matched by the management scope.

    ``domain_creation_scopes``, ``domain_modification_scopes``, and
    ``domain_deletion_scopes`` are three independent flat governed-tag-key scopes
    (mirroring the group creation/modification/deletion gates): creation gates
    creating declared ``resources.domains`` missing from the workspace, modification
    gates metadata updates of declared domains that already exist, and deletion
    independently selects actual-only domains for removal. Any active scope fetches
    and diffs domain state; each gate acts alone, so a domain outside the creation
    scope is never created even when it matches the modification scope, and vice
    versa. Deletions prompt for confirmation unless ``force`` is set.

    The deprecated ``*_for_namespaces`` strings scope each enabled domain to a
    subset of the configured namespaces. Each comma-separated entry is either a
    bare catalog name (covers everything under that catalog) or a qualified
    ``catalog.schema`` name (covers that schema and its children). ``"*"`` (the
    default) means "all configured catalogs". A filter has no effect unless its
    paired ``enable_*`` flag is set. Unknown catalog/schema names raise
    ``ValueError`` early. Function securables are never namespace-filtered —
    they're engine-managed and flow through all scopes.

    ``retain_tag_prefixes`` is a comma-separated list of tag-key prefixes the
    engine must never remove from securables, even when those tags are absent
    from config (it may still add/update them). Defaults to ``"class."`` to
    protect UC auto data classification tags. An empty string allows the engine
    to remove any unconfigured tag.

    The groups domain is the first domain orchestrated (before governed tags),
    gated by two orthogonal scopes. ``group_creation_scopes`` creates configured
    groups that don't yet exist (the engine auto-receives the MANAGER role on
    groups it creates). ``group_modification_scopes`` reconciles the membership of
    *existing* groups — adding missing members and removing members absent from
    config (an empty members list removes all); it never creates or deletes groups
    and requires the MANAGER role on each modified group. The deprecated
    ``enable_group_creation`` / ``enable_group_management`` booleans map onto these.
    A configured group that doesn't exist is a fatal error under modification unless
    creation is also enabled; existing externally-managed (IdP-provisioned) groups
    are a fatal error. With neither scope the group domain is inert. Both scopes
    require the account SCIM proxy, so combining them with
    ``use_workspace_scim=True`` raises immediately.

    ``ignore_unresolvable_principals`` is a comma-separated list of actual-state
    (UC-side) principal identifiers — usernames, service-principal
    application_ids, or group display names — whose resolution-failure warning is
    suppressed across the privileges, securables (owner), governed-tags
    (assigners), and domains (business/technical owners) domains. Primarily for
    Databricks-managed system service principals that appear in system tables but
    aren't resolvable via SCIM. Empty by default.

    ``warn_on_nonexistent_securables`` changes missing non-function securables
    outside ``securable_creation_scopes`` from fatal errors to non-fatal warnings.
    Every operation targeting the missing object or a descendant is removed from
    the plan. In-scope creation requests that lack required configuration remain
    fatal validation errors.
    """
    config = load_config(config_dir, ref_override_strategy)
    settings = _build_run_context(
        config,
        system_catalog=system_catalog,
        information_schema=information_schema,
        per_catalog_information_schema=per_catalog_information_schema,
        timezone=timezone,
        dry_run=dry_run,
        use_workspace_scim=use_workspace_scim,
        skip_users_fetch=skip_users_fetch,
        enable_tag_management=enable_tag_management,
        enable_taggable_management=enable_taggable_management,
        enable_taggable_creation=enable_taggable_creation,
        enable_privilege_management=enable_privilege_management,
        enable_governed_tag_deletion=enable_governed_tag_deletion,
        enable_policy_deletion=enable_policy_deletion,
        enable_group_creation=enable_group_creation,
        enable_group_management=enable_group_management,
        enable_group_deletion=enable_group_deletion,
        ignore_unresolvable_principals=ignore_unresolvable_principals,
        manage_tags_for_namespaces=manage_tags_for_namespaces,
        manage_privileges_for_namespaces=manage_privileges_for_namespaces,
        manage_taggables_for_namespaces=manage_taggables_for_namespaces,
        create_taggables_for_namespaces=create_taggables_for_namespaces,
        delete_policies_for_namespaces=delete_policies_for_namespaces,
        tag_management_scopes=tag_management_scopes,
        tag_assignment_scopes=tag_assignment_scopes,
        privilege_management_scopes=privilege_management_scopes,
        securable_modification_scopes=securable_modification_scopes,
        securable_creation_scopes=securable_creation_scopes,
        policy_deletion_scopes=policy_deletion_scopes,
        group_creation_scopes=group_creation_scopes,
        group_modification_scopes=group_modification_scopes,
        group_deletion_scopes=group_deletion_scopes,
        governed_tag_deletion_scopes=governed_tag_deletion_scopes,
        domain_creation_scopes=domain_creation_scopes,
        domain_modification_scopes=domain_modification_scopes,
        domain_deletion_scopes=domain_deletion_scopes,
        retain_tag_prefixes=retain_tag_prefixes,
        warn_on_nonexistent_securables=warn_on_nonexistent_securables,
        ref_override_strategy=ref_override_strategy,
        force=force,
        max_parallel_changes=max_parallel_changes,
    )

    # Build the two live helpers once; they are threaded into both fetch_actual_state
    # (which populates their caches) and _execute_changes (which reuses the same
    # instances, so the resolver and SQL/API execution see the already-seeded caches).
    uc_helper = UnityCatalogHelper(
        workspace_client,
        warehouse_id,
        system_catalog=settings.system_catalog,
        information_schema=settings.information_schema,
        per_catalog_information_schema=settings.per_catalog_information_schema,
    )
    ws_helper = WorkspaceHelper(
        workspace_client,
        use_workspace_scim=settings.use_workspace_scim,
        manage_groups=settings.group_domain_active and bool(config.groups),
        manage_domain_owners=settings.manage_domain_owners,
        skip_users_fetch=settings.skip_users_fetch,
    )

    change_logger = ChangeLogger(dry_run=dry_run, logger=_logger)
    change_logger.log_banner()
    _logger.info(
        "  Fetching current state from workspace (this can take several minutes)..."
    )
    actual_state = fetch_actual_state(config, uc_helper, ws_helper, settings)
    _logger.info("  Successfully fetched current state")

    result = _execute_changes(
        config, actual_state, uc_helper, ws_helper, settings, change_logger
    )

    change_logger.log_errors_section()
    change_logger.log_summary()
    if change_logger.has_errors:
        raise ExecutionBatchError(change_logger.errors)
    return result
