"""Match the viewer's policies against tags, and reconcile grants with Unity Catalog.

Grant matching mirrors the engine's privileges compiler: a grant policy's privileges
expand their abstractions (``READ`` -> ``select``, ...), ``USE CATALOG`` and
``USE SCHEMA`` cascade to the catalog and schema, ``SECURABLE_TYPE_PRIVILEGE_MAP``
filters out privileges a securable type cannot hold, and column tags never drive a grant.
One ``GrantMatch`` is kept per witness (the tags that justified it).

Reconciliation compares those policy matches with the privileges Unity Catalog holds
(``securable_privileges``):

- A policy match with an actual privilege is attributed to the policy.
- An actual privilege no policy produces is a manual grant. It is explained by a
  synthetic ``CompiledGrantPolicy`` with ``origin="direct"``.
- A policy match with no actual privilege is drift: it is reported, never counted as
  access.

FGAC matching keeps a mask or filter on every table in its scope whose own tags satisfy
the table predicate, and whose every match alias finds at least one column.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from abac_viewer.backend.engine.conditions import TagCondition
from abac_viewer.backend.engine.dump_policies import ParsedFgacPolicy, ParsedGrantPolicy
from abac_viewer.backend.engine.model import (
    CompiledGrantPolicy,
    FgacMatch,
    GrantDrift,
    GrantMatch,
    Securable,
)
from uc_abac.types import (
    ABSTRACT_PRIVILEGE_MAP,
    SECURABLE_TYPE_PRIVILEGE_MAP,
    AbstractedPrivilegeType,
    PrivilegeType,
    SecurableType,
)

DIRECT_GRANT_NAME = "manual grant"

TagsBySecurable = Mapping[str, Mapping[str, str]]
Securables = Mapping[str, Securable]
MatchKey = tuple[str, str, str]


@dataclass(frozen=True)
class ActualPrivilege:
    """A privilege Unity Catalog holds on a securable, for one principal."""

    principal: str
    privilege: str
    securable_full_name: str
    securable_type: str

    @property
    def key(self) -> MatchKey:
        return (self.principal, self.privilege, self.securable_full_name)


@dataclass(frozen=True)
class GrantReconciliation:
    """The grant matches the model keeps, the drift, and the synthetic direct policies."""

    grant_matches: tuple[GrantMatch, ...]
    drift: tuple[GrantDrift, ...]
    direct_policies: tuple[CompiledGrantPolicy, ...]


# ---------------------------------------------------------------------------
# scope and privilege helpers
# ---------------------------------------------------------------------------


def _in_scope(full_name: str, scope: str) -> bool:
    return full_name == scope or full_name.startswith(f"{scope}.")


def _expand_privilege(privilege: str) -> tuple[str, ...]:
    """A declared privilege as the concrete UC privileges it stands for."""
    try:
        abstraction = AbstractedPrivilegeType(privilege)
    except ValueError:
        return (privilege,)
    return tuple(sorted(p.value for p in ABSTRACT_PRIVILEGE_MAP[abstraction]))


def _expand_privileges(privileges: Sequence[str]) -> tuple[str, ...]:
    return tuple(p for privilege in privileges for p in _expand_privilege(privilege))


def _grant_target(privilege: str, sec_type: str, full_name: str) -> tuple[str, str]:
    """``USE CATALOG`` cascades to the catalog and ``USE SCHEMA`` to the schema, as in
    the privileges compiler's target resolution."""
    if privilege == PrivilegeType.USE_CATALOG.value:
        return "catalog", full_name.split(".", 1)[0]
    if privilege == PrivilegeType.USE_SCHEMA.value:
        parts = full_name.split(".")
        if len(parts) >= 2:
            return "schema", ".".join(parts[:2])
    return sec_type, full_name


def _privilege_allowed_on(privilege: str, sec_type: str) -> bool:
    """Whether UC allows ``privilege`` on ``sec_type``; an unknown privilege or type
    (the loader warns about those) is never allowed."""
    try:
        allowed = SECURABLE_TYPE_PRIVILEGE_MAP.get(SecurableType(sec_type.upper()))
        return allowed is None or PrivilegeType(privilege) in allowed
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# grant matching
# ---------------------------------------------------------------------------


def _emit(
    policy: CompiledGrantPolicy,
    privileges: Sequence[str],
    sec_type: str,
    full_name: str,
    witness: tuple[tuple[str, str], ...],
) -> list[GrantMatch]:
    """One match per principal, expanded privilege, and in-scope, allowed target."""
    matches: list[GrantMatch] = []
    for principal in policy.to:
        for privilege in privileges:
            target_type, target_name = _grant_target(privilege, sec_type, full_name)
            if not _in_scope(target_name, policy.parent_full_name):
                continue
            if not _privilege_allowed_on(privilege, target_type):
                continue
            matches.append(
                GrantMatch(
                    policy_id=policy.policy_id,
                    securable_full_name=target_name,
                    securable_type=target_type,
                    privilege=privilege,
                    principal=principal,
                    matched_tags=witness,
                    matched_securable_full_name=full_name,
                )
            )
    return matches


def _is_tagless(condition: TagCondition) -> bool:
    """No tag atoms and nothing unsupported: the policy applies to its parent scope."""
    return not (
        condition.has_tags
        or condition.has_any_of_tags
        or condition.has_none_of_tags
        or condition.unsupported
    )


def _parent_scoped_matches(
    policy: CompiledGrantPolicy,
    privileges: Sequence[str],
    securables: Securables,
) -> list[GrantMatch]:
    parent = securables.get(policy.parent_full_name)
    sec_type = parent.securable_type if parent else "catalog"
    if policy.for_securable_type not in (None, sec_type):
        return []
    return _emit(policy, privileges, sec_type, policy.parent_full_name, ())


def _admits(policy: CompiledGrantPolicy, sec: Securable, full_name: str) -> bool:
    """Whether a tagged grant policy's type and scope admit a securable."""
    if policy.for_securable_type is not None and (
        sec.securable_type != policy.for_securable_type
    ):
        return False
    return _in_scope(full_name, policy.parent_full_name)


def _tagged_matches(
    parsed: ParsedGrantPolicy,
    privileges: Sequence[str],
    securables: Securables,
    tags_by_securable: TagsBySecurable,
) -> list[GrantMatch]:
    matches: list[GrantMatch] = []
    for full_name, sec in securables.items():
        if sec.securable_type == "column":
            continue
        actual = tags_by_securable.get(full_name, {})
        if not actual or not _admits(parsed.policy, sec, full_name):
            continue
        if not parsed.condition.matches(actual):
            continue
        witness = parsed.condition.witness(actual)
        matches.extend(
            _emit(parsed.policy, privileges, sec.securable_type, full_name, witness)
        )
    return matches


def _dedupe_key(match: GrantMatch) -> tuple[str, ...]:
    return (
        match.policy_id,
        match.securable_full_name,
        match.privilege,
        match.principal,
        match.matched_securable_full_name,
    )


def _dedupe_matches(matches: Sequence[GrantMatch]) -> list[GrantMatch]:
    """Drop duplicate emissions but keep one row per witness: the matched securable is
    part of the key, so a cascaded grant (e.g. USE CATALOG) keeps every tag match that
    would justify it."""
    keys = {}
    for match in matches:
        keys.setdefault(_dedupe_key(match), match)
    return list(keys.values())


def match_grant_policy(
    parsed: ParsedGrantPolicy,
    securables: Securables,
    tags_by_securable: TagsBySecurable,
) -> list[GrantMatch]:
    """The grant matches a policy produces against the actual tags.

    A tagless policy applies to its parent securable. Otherwise it applies to every
    tagged securable in its scope that its condition matches.
    """
    privileges = _expand_privileges(parsed.policy.privileges)
    if _is_tagless(parsed.condition):
        matches = _parent_scoped_matches(parsed.policy, privileges, securables)
    else:
        matches = _tagged_matches(parsed, privileges, securables, tags_by_securable)
    return _dedupe_matches(matches)


# ---------------------------------------------------------------------------
# FGAC (mask and filter) matching
# ---------------------------------------------------------------------------


def index_columns(securables: Securables) -> dict[str, tuple[Securable, ...]]:
    """Column securables grouped by their table's full name."""
    grouped: dict[str, tuple[Securable, ...]] = {}
    for sec in securables.values():
        if sec.securable_type == "column" and sec.parent_full_name:
            grouped[sec.parent_full_name] = (
                *grouped.get(sec.parent_full_name, ()),
                sec,
            )
    return grouped


def _column_hits(
    table_full_name: str,
    condition: TagCondition,
    columns: Sequence[Securable],
    tags_by_securable: TagsBySecurable,
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """The columns of a table that satisfy an alias condition, with their witnesses."""
    hits = []
    for column in columns:
        column_tags = tags_by_securable.get(column.full_name, {})
        if condition.matches(column_tags):
            name = column.full_name.removeprefix(f"{table_full_name}.")
            hits.append((name, condition.witness(column_tags)))
    return tuple(hits)


def _alias_matches(
    table_full_name: str,
    alias_conditions: Sequence[tuple[str, TagCondition]],
    columns: Sequence[Securable],
    tags_by_securable: TagsBySecurable,
) -> tuple[tuple[str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]], ...] | None:
    """Each alias with its matching columns, or ``None`` when any alias matches none."""
    matched = []
    for alias, condition in alias_conditions:
        hits = _column_hits(table_full_name, condition, columns, tags_by_securable)
        if not hits:
            return None
        matched.append((alias, hits))
    return tuple(matched)


def _matched_columns(
    policy_type: str,
    aliases: tuple[
        tuple[str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]], ...
    ],
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """A mask's columns are those of its first (``on_column``) alias; a filter's are
    every alias's columns, in alias order."""
    if not aliases:
        return ()
    if policy_type == "mask":
        return aliases[0][1]
    return tuple(hit for _alias, hits in aliases for hit in hits)


def match_fgac_policy(
    parsed: ParsedFgacPolicy,
    securables: Securables,
    columns_by_table: Mapping[str, Sequence[Securable]],
    tags_by_securable: TagsBySecurable,
) -> list[FgacMatch]:
    """The tables a mask or filter applies to, with the columns its aliases matched."""
    policy = parsed.policy
    matches: list[FgacMatch] = []
    for full_name, sec in securables.items():
        if sec.securable_type != "table" or not _in_scope(
            full_name, policy.parent_full_name
        ):
            continue
        table_tags = tags_by_securable.get(full_name, {})
        if not parsed.condition.matches(table_tags):
            continue
        aliases = _alias_matches(
            full_name,
            parsed.alias_conditions,
            columns_by_table.get(full_name, ()),
            tags_by_securable,
        )
        if aliases is None:
            continue
        matches.append(
            FgacMatch(
                policy_id=policy.policy_id,
                table_full_name=full_name,
                matched_table_tags=parsed.condition.witness(table_tags),
                matched_columns=_matched_columns(policy.policy_type, aliases),
                matched_aliases=aliases,
            )
        )
    return matches


# ---------------------------------------------------------------------------
# reconciliation with the privileges Unity Catalog holds
# ---------------------------------------------------------------------------


def _match_key(match: GrantMatch) -> MatchKey:
    return (match.principal, match.privilege, match.securable_full_name)


def _direct_policy_id(principal: str, securable_full_name: str) -> str:
    return f"direct:{principal}:{securable_full_name}"


def _direct_policy(group: tuple[ActualPrivilege, ...]) -> CompiledGrantPolicy:
    """The synthetic grant policy explaining one principal's manual grants on one
    securable."""
    first = group[0]
    return CompiledGrantPolicy(
        policy_id=_direct_policy_id(first.principal, first.securable_full_name),
        name=DIRECT_GRANT_NAME,
        parent_full_name=first.securable_full_name,
        has_tags=(),
        has_any_of_tags=(),
        privileges=tuple(sorted({p.privilege for p in group})),
        to=(first.principal,),
        for_securable_type=None,
        expiry_date=None,
        comment=None,
        origin="direct",
    )


def _direct_match(privilege: ActualPrivilege) -> GrantMatch:
    return GrantMatch(
        policy_id=_direct_policy_id(privilege.principal, privilege.securable_full_name),
        securable_full_name=privilege.securable_full_name,
        securable_type=privilege.securable_type,
        privilege=privilege.privilege,
        principal=privilege.principal,
        matched_tags=(),
        matched_securable_full_name=privilege.securable_full_name,
    )


def _grouped_by_grantee(
    privileges: Sequence[ActualPrivilege],
) -> dict[tuple[str, str], tuple[ActualPrivilege, ...]]:
    grouped: dict[tuple[str, str], tuple[ActualPrivilege, ...]] = {}
    for privilege in privileges:
        group_key = (privilege.principal, privilege.securable_full_name)
        grouped[group_key] = (*grouped.get(group_key, ()), privilege)
    return grouped


def _drift(
    policy_matches: Sequence[GrantMatch], actual_keys: set[MatchKey]
) -> tuple[GrantDrift, ...]:
    """Policy matches with no actual privilege, one per (policy, securable, privilege,
    principal)."""
    missing = [m for m in policy_matches if _match_key(m) not in actual_keys]
    drift = {
        (m.policy_id, m.securable_full_name, m.privilege, m.principal): GrantDrift(
            policy_id=m.policy_id,
            securable_full_name=m.securable_full_name,
            securable_type=m.securable_type,
            privilege=m.privilege,
            principal=m.principal,
        )
        for m in missing
    }
    return tuple(drift.values())


def reconcile_grants(
    policy_matches: Sequence[GrantMatch],
    actual: Sequence[ActualPrivilege],
) -> GrantReconciliation:
    """Attribute actual privileges to policies, explain manual grants, and report drift.

    See the module docstring for the three cases.
    """
    actual_keys = {p.key for p in actual}
    policy_keys = {_match_key(m) for m in policy_matches}
    attributed = tuple(m for m in policy_matches if _match_key(m) in actual_keys)
    manual = tuple(p for p in actual if p.key not in policy_keys)
    groups = _grouped_by_grantee(manual)
    return GrantReconciliation(
        grant_matches=attributed + tuple(_direct_match(p) for p in manual),
        drift=_drift(policy_matches, actual_keys),
        direct_policies=tuple(_direct_policy(group) for group in groups.values()),
    )
