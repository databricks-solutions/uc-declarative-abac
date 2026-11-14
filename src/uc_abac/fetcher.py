from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from uc_abac.configs import ResourcesConfig
from uc_abac.helpers import UnityCatalogHelper, WorkspaceHelper
from uc_abac.resources.domains import Domain
from uc_abac.resources.governed_tags import (
    GovernedTag,
    collect_referenced_tag_keys,
    compile_desired_governed_tags,
)
from uc_abac.resources.policies import Policy
from uc_abac.resources.principals import (
    Group,
    Principal,
    collect_referenced_principal_names,
    compile_desired_groups,
)
from uc_abac.resources.privileges import SecurablePrivilege
from uc_abac.resources.securables import (
    Securable,
    SecurableAttributes,
    compile_desired_attributes,
)
from uc_abac.resources.tags import SecurableTag
from uc_abac.types import SecurableType
from uc_abac.utils import (
    RunContext,
    Scope,
    is_account_users_group,
    parse_flat_scope,
    parse_hierarchical_scope,
    run_date_for_timezone,
)


@dataclass(frozen=True)
class ActualState:
    """Fetched workspace/UC actual state — a pure "current state" view.

    Every field is a fetched state set (plus ``principals``, the resolved
    ``WorkspaceHelper.get_principals()`` snapshot). This carries **no** execution
    handles: the live ``UnityCatalogHelper`` / ``WorkspaceHelper`` are built once by
    ``run()`` and threaded separately into ``fetch_actual_state`` (which populates
    their caches) and ``_execute_changes`` (which reuses the same instances), so a
    downstream consumer can read this state view without touching the helpers.

    Produced by ``fetch_actual_state``. When that function is called with
    ``settings=None`` every field reflects a full, unscoped fetch of its domain;
    when ``run()`` passes a ``RunContext`` the sets are scoped/gated exactly as the
    deploy pipeline requires (so e.g. ``privileges`` is empty when privilege
    management is off, and ``governed_tags`` covers only configured names).
    """

    groups: frozenset[Group]
    all_account_groups: frozenset[Group]
    governed_tags: frozenset[GovernedTag]
    domains: frozenset[Domain]
    securables: frozenset[Securable]
    attributes: frozenset[SecurableAttributes]
    tags: frozenset[SecurableTag]
    policies: frozenset[Policy]
    privileges: frozenset[SecurablePrivilege]
    principals: dict[str, Principal]


def _full_fetch_context() -> RunContext:
    """A ``RunContext`` that makes ``fetch_actual_state`` fetch everything.

    Used when ``fetch_actual_state`` is called with ``settings=None`` (a downstream
    "current state" view): every scope is match-all so no domain is gated out and
    all RFA / column-comment targets are fetched. The run date defaults to today in
    UTC; the non-fetch fields (retain prefixes, force, …) are inert defaults.
    """
    all_hierarchical = parse_hierarchical_scope("*")
    all_flat = parse_flat_scope("*")
    return RunContext(
        tag_management_scope=all_hierarchical,
        tag_assignment_scope=all_hierarchical,
        privilege_management_scope=all_hierarchical,
        securable_modification_scope=all_hierarchical,
        securable_creation_scope=all_hierarchical,
        policy_deletion_scope=all_hierarchical,
        group_creation_scope=all_flat,
        group_modification_scope=all_flat,
        group_deletion_scope=all_flat,
        governed_tag_deletion_scope=all_flat,
        domain_creation_scope=all_flat,
        domain_modification_scope=all_flat,
        domain_deletion_scope=all_flat,
        run_date=run_date_for_timezone("UTC"),
        retain_prefixes=frozenset(),
        ignore_unresolvable=frozenset(),
        system_catalog="system",
        use_workspace_scim=False,
        skip_users_fetch=False,
        dry_run=False,
        force=False,
        max_parallel_changes=8,
        manage_domain_owners=True,
        warn_on_nonexistent_securables=False,
    )


@dataclass(frozen=True)
class _GroupFetchSets:
    """The name/id sets ``WorkspaceHelper.fetch_actual_groups`` takes: which groups to
    return (identity), and which of those to fetch members and assumers for."""

    names: frozenset[str]
    ids: frozenset[str]
    member_names: frozenset[str]
    member_ids: frozenset[str]
    assumer_names: frozenset[str]
    assumer_ids: frozenset[str]


def _groups_managing(field: str, groups: set[Group], scope: Scope) -> list[Group]:
    """The in-``scope`` groups whose ``field`` (``members``/``assumers``) is supplied."""
    return [
        g
        for g in groups
        if getattr(g, field) is not None and scope.matches(g.display_name)
    ]


def _deploy_group_fetch_sets(
    desired_groups: set[Group], ctx: RunContext
) -> _GroupFetchSets:
    """Group fetch sets for a deploy: declared groups only.

    Membership and assumers are authoritative only when supplied, so each is fetched
    only for the groups whose field is non-None AND in the modification scope (the only
    scope that reconciles them). Identity comes from the principal-fetch caches (no
    extra call).
    """
    scope = ctx.group_modification_scope
    members = _groups_managing("members", desired_groups, scope)
    assumers = _groups_managing("assumers", desired_groups, scope)
    return _GroupFetchSets(
        names=frozenset(g.display_name for g in desired_groups),
        ids=frozenset(g.id for g in desired_groups if g.id),
        member_names=frozenset(g.display_name for g in members),
        member_ids=frozenset(g.id for g in members if g.id),
        assumer_names=frozenset(g.display_name for g in assumers),
        assumer_ids=frozenset(g.id for g in assumers if g.id),
    )


def _full_group_fetch_sets(
    config: ResourcesConfig, desired_groups: set[Group]
) -> _GroupFetchSets:
    """Group fetch sets for a full fetch: every group referenced anywhere in config.

    Declared groups plus every principal name config references (owners, policy
    recipients, domain owners, assigners, members, assumers) — the helper keeps only
    names that are real account groups, so users/SPs in the set are harmless. Members
    and assumers are fetched for all of them. ``account users`` is always excluded
    (see ``is_account_users_group``). Declared ids are kept so an id-declared group
    whose display name has drifted is still matched.
    """
    names = frozenset(
        name
        for name in {g.display_name for g in desired_groups}
        | collect_referenced_principal_names(config)
        if not is_account_users_group(name)
    )
    ids = frozenset(
        g.id
        for g in desired_groups
        if g.id and not is_account_users_group(g.display_name)
    )
    return _GroupFetchSets(names, ids, names, ids, names, ids)


def fetch_actual_state(
    config: ResourcesConfig,
    uc_helper: UnityCatalogHelper,
    ws_helper: WorkspaceHelper,
    settings: RunContext | None = None,
) -> ActualState:
    """Fetch the current workspace/UC state and return it as a pure ``ActualState``.

    Populates the two passed-in helpers' caches in place (``fetch_principals``
    builds the principal-id maps that ``_execute_changes`` later reuses for
    resolution and execution — so the orchestrator threads the *same* helper
    instances into both). The fetch is scoped from ``config`` plus ``settings``:
    catalog names, configured governed-tag/group names, RFA and data classification
    targets, and column-comment tables are derived from config (via the pure
    config-only compilers), while ``settings`` gates which domains are fetched at all.

    ``settings=None`` fetches the complete actual state for every domain — the
    downstream "current state" view. It also widens two config-scoped fetches from
    "what config declares" to "what config references": group members and assumers
    are fetched for every group referenced anywhere in config (except ``account
    users``; see ``_full_group_fetch_sets``), and governed-tag assigners for every
    tag key referenced anywhere in config (``collect_referenced_tag_keys``). Callers
    wanting that complete view must build the helpers with ``manage_groups=True`` /
    ``manage_domain_owners=True`` — even when config declares no groups — so the
    group and domain-owner id maps exist.

    Securable attributes, domains, and groups are read after the principal fetch
    (``fetch_actual_domains`` / ``fetch_actual_groups`` map owner/member numeric ids
    back to principals via the just-built caches), so running them concurrently
    with the principal fetch would read owners/members as empty and re-add them on
    every run.
    """
    full_fetch = settings is None
    ctx = _full_fetch_context() if full_fetch else settings

    catalog_names = [c.full_name for c in config.catalogs.values()]
    desired_groups = compile_desired_groups(config, run_date=ctx.run_date)
    # Assigner rule sets are fetched only for tags managing them (the full fetch reads
    # every declared or referenced tag's assigners for the current-state view).
    governed_tag_fetch_names = {
        gt.name
        for gt in compile_desired_governed_tags(config)
        if full_fetch or gt.assigners is not None
    }
    if full_fetch:
        governed_tag_fetch_names |= collect_referenced_tag_keys(config)
    desired_attributes = compile_desired_attributes(config)
    # RFA targets restrict the attribute fetch to securables that declare
    # ``rfa_destinations``. Non-function securables are gated by the securable-
    # modification scope (RFA is a managed attribute), but FUNCTION targets are always
    # fetched — functions are engine-managed independently of the scope. Without this
    # a function's actual RFA state stays ``None`` when the scope is empty, and an
    # explicit empty list ("remove all") silently no-ops against a ``None`` actual.
    rfa_targets: set[tuple[SecurableType, str]] = {
        (a.securable_type, a.full_name)
        for a in desired_attributes
        if a.rfa_destinations is not None
        and (
            ctx.enable_securable_modification
            or a.securable_type == SecurableType.FUNCTION
        )
    }
    # Catalogs managing Data Classification (enabled, or only auto-tagging, which
    # needs to know whether a config exists). These are managed catalog attributes,
    # so they share the securable-modification gate.
    data_classification_targets: set[str] = {
        a.full_name
        for a in desired_attributes
        if (
            a.data_classification_enabled is not None
            or a.data_classification_auto_tagging_tags is not None
        )
        and ctx.enable_securable_modification
    }
    # Parent tables of every in-scope column that declares a comment. Column comments
    # are a managed (securable) attribute, so — unlike rfa_targets, which has a FUNCTION
    # exception — they are fetched only for tables in the securable-modification scope.
    column_comment_tables: set[str] = {
        a.full_name.rpartition(".")[0]
        for a in desired_attributes
        if a.securable_type == SecurableType.COLUMN
        and a.comment is not None
        and ctx.securable_modification_scope.matches(a.full_name)
    }

    # actual_tags is needed by either the tags domain (for the diff) or the privileges
    # domain (for policy matching against on-disk tag state when tag assignment/
    # management is off). The effective assignment scope (union) covers both.
    need_actual_tags = ctx.enable_tag_assignment or ctx.enable_privilege_management
    with ThreadPoolExecutor() as pool:
        actual_securables_f = pool.submit(
            uc_helper.fetch_actual_securables,
            catalog_names,
            rfa_targets,
            column_comment_tables,
            data_classification_targets=data_classification_targets,
        )
        actual_policies_f = pool.submit(uc_helper.fetch_actual_policies, catalog_names)
        actual_governed_tags_f = pool.submit(
            ws_helper.fetch_actual_governed_tags,
            governed_tag_fetch_names,
        )
        principals_f = pool.submit(ws_helper.fetch_principals)
        actual_tags_f = (
            pool.submit(uc_helper.fetch_actual_tags, catalog_names)
            if need_actual_tags
            else None
        )
        actual_privs_f = (
            pool.submit(uc_helper.fetch_actual_privileges, catalog_names)
            if ctx.enable_privilege_management
            else None
        )

        actual_securables, actual_attributes = actual_securables_f.result()
        actual_policies = actual_policies_f.result()
        actual_governed_tags = actual_governed_tags_f.result()
        principals_f.result()
        actual_tags = actual_tags_f.result() if actual_tags_f is not None else set()
        actual_privileges = (
            actual_privs_f.result() if actual_privs_f is not None else set()
        )
    actual_domains = (
        ws_helper.fetch_actual_domains() if ctx.domain_workflow_active else set()
    )

    group_fetch = (
        _full_group_fetch_sets(config, desired_groups)
        if full_fetch
        else _deploy_group_fetch_sets(desired_groups, ctx)
    )
    actual_groups = (
        ws_helper.fetch_actual_groups(
            group_fetch.names,
            group_fetch.ids,
            member_fetch_names=group_fetch.member_names,
            member_fetch_ids=group_fetch.member_ids,
            assumer_fetch_names=group_fetch.assumer_names,
            assumer_fetch_ids=group_fetch.assumer_ids,
        )
        if ctx.group_domain_active
        else set()
    )
    # Group deletion needs the full account-group inventory (identity + provenance
    # only) to find Databricks-managed groups absent from config. Cheap — built from
    # caches populated during fetch_principals, no extra API calls.
    all_account_groups = (
        ws_helper.list_account_groups() if ctx.enable_group_deletion else set()
    )

    return ActualState(
        groups=frozenset(actual_groups),
        all_account_groups=frozenset(all_account_groups),
        governed_tags=frozenset(actual_governed_tags),
        domains=frozenset(actual_domains),
        securables=frozenset(actual_securables),
        attributes=frozenset(actual_attributes),
        tags=frozenset(actual_tags),
        policies=frozenset(actual_policies),
        privileges=frozenset(actual_privileges),
        principals=ws_helper.get_principals(),
    )
