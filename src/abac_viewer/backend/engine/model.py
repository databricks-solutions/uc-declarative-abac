"""Factored data model derived from a uc-declarative-abac config tree.

The model contains factored membership, tag, policy, and securable relations.
Everything carries provenance (YAML file + line) so every chain node can link
back to the declaration that caused it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The Databricks system group that means "every principal". A mask/filter
# policy with no explicit 'to' defaults to it (uc-declarative-abac semantics).
ALL_USERS_GROUP = "account users"
SYSTEM_GROUPS = frozenset({ALL_USERS_GROUP, "account admins"})


@dataclass(frozen=True)
class Provenance:
    """Where a declaration lives in the config tree."""

    file: str  # path relative to the config root
    line: int | None = None  # best-effort 1-indexed line of the declaration


@dataclass(frozen=True)
class Securable:
    full_name: str  # dot-delimited UC path, e.g. cat.schema.table
    securable_type: str  # catalog | schema | table | volume | function | column
    parent_full_name: str | None
    provenance: Provenance | None = None
    comment: str | None = None
    # column-only extras
    data_type: str | None = None


@dataclass(frozen=True)
class TagAssignment:
    """Relation 2 — a tag declared on a securable (own tags; no inheritance,
    mirroring the tool's compiler which emits tags per-object only)."""

    securable_full_name: str
    securable_type: str
    tag_name: str
    tag_value: str
    provenance: Provenance | None = None


@dataclass(frozen=True)
class MembershipEdge:
    """Relation 1 (closure) — member belongs to group, directly or transitively.

    ``via`` is the group chain from member to group, e.g. a user in
    analysts_emea ⊂ analysts has closure row (user, analysts,
    via=(analysts_emea, analysts)).
    """

    member: str  # user / SP / group display name
    group: str
    via: tuple[str, ...]
    provenance: Provenance | None = None

    @property
    def direct(self) -> bool:
        return len(self.via) == 1


@dataclass(frozen=True)
class CompiledGrantPolicy:
    """Relation 3 (grant flavor) — a grant policy, normalized."""

    policy_id: str  # "<parent_full_name>#<name>"
    name: str
    parent_full_name: str  # securable the policy is attached to
    has_tags: tuple[tuple[str, str], ...]  # AND atoms; value '*' = presence
    has_any_of_tags: tuple[tuple[str, str], ...]  # OR atoms
    privileges: tuple[str, ...]  # as declared (may include abstractions e.g. 'use')
    to: tuple[str, ...]
    for_securable_type: str | None
    expiry_date: str | None
    comment: str | None
    provenance: Provenance | None = None
    # "policy" for a declared grant policy; "direct" for the synthetic entry that
    # explains an actual privilege no grant policy produces (a manual GRANT).
    origin: str = "policy"


@dataclass(frozen=True)
class FgacColumnArgument:
    """One ordered function argument from an FGAC policy."""

    kind: str  # alias | constant
    alias: str | None = None
    has_tags: tuple[tuple[str, str], ...] = ()
    has_any_of_tags: tuple[tuple[str, str], ...] = ()
    constant: bool | int | float | str | None = None
    constant_type: str | None = None


@dataclass(frozen=True)
class CompiledFgacPolicy:
    """Relation 3 (mask/filter flavor) — a mask or filter policy, normalized."""

    policy_id: str
    name: str
    policy_type: str  # mask | filter
    parent_full_name: str
    has_tags: tuple[tuple[str, str], ...]
    has_any_of_tags: tuple[tuple[str, str], ...]
    function: str
    to: tuple[str, ...]  # defaults to (ALL_USERS_GROUP,)
    exceptions: tuple[str, ...]
    column_arguments: tuple[FgacColumnArgument, ...]
    # Every alias column predicate in declaration order. For masks the first
    # alias identifies the masked column and the rest are function arguments;
    # for filters every alias is a function argument.
    match_columns: tuple[
        tuple[
            str,
            tuple[tuple[str, str], ...],
            tuple[tuple[str, str], ...],
        ],
        ...,
    ]
    # Compatibility projections for callers interested in the mask target.
    match_column_has_tags: tuple[tuple[str, str], ...]
    match_column_has_any_of_tags: tuple[tuple[str, str], ...]
    comment: str | None
    provenance: Provenance | None = None


@dataclass(frozen=True)
class GrantMatch:
    """Relation 4 — one privilege a grant policy emits on a securable.

    Mirrors uc_abac.privileges.compiler semantics exactly (verified
    by test_engine_matches_tool_compiler), but keeps the causing policy — the
    provenance UC itself discards on apply.
    """

    policy_id: str
    securable_full_name: str  # grant target (use_catalog/use_schema cascade up)
    securable_type: str
    privilege: str  # concrete UC privilege, abstractions expanded
    principal: str  # as declared in the policy's 'to'
    # tag assignments that satisfied the predicate ((tag_name, tag_value) of
    # the matched securable); empty for a tagless direct grant
    matched_tags: tuple[tuple[str, str], ...]
    # the securable whose tags matched the predicate (== securable_full_name
    # except for cascaded use_catalog/use_schema grants)
    matched_securable_full_name: str = ""


@dataclass(frozen=True)
class FgacMatch:
    """Relation 4 (FGAC flavor) — a mask/filter policy applying to a table
    (and, for masks, the columns matched by the policy's column alias)."""

    policy_id: str
    table_full_name: str
    matched_table_tags: tuple[tuple[str, str], ...]
    # mask only: columns of the table whose tags satisfy the column alias
    # predicate, with the tag atoms that matched, e.g. {"email": (("pii","email"),)}
    matched_columns: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    # Every alias and all columns matching it, preserving argument order.
    matched_aliases: tuple[
        tuple[
            str,
            tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
        ],
        ...,
    ] = ()


@dataclass(frozen=True)
class GrantDrift:
    """A privilege a grant policy matches (against the actual tags) that Unity
    Catalog does not hold — typically a config change not yet deployed. Drift is
    reported, never counted as access."""

    policy_id: str
    securable_full_name: str
    securable_type: str
    privilege: str
    principal: str


@dataclass
class FactoredModel:
    """The full derived model for one config revision."""

    revision: str
    source: str  # where the model was loaded from, e.g. the dump target schema
    securables: dict[str, Securable] = field(default_factory=dict)
    tag_assignments: list[TagAssignment] = field(default_factory=list)
    membership_closure: list[MembershipEdge] = field(default_factory=list)
    grant_policies: dict[str, CompiledGrantPolicy] = field(default_factory=dict)
    fgac_policies: dict[str, CompiledFgacPolicy] = field(default_factory=dict)
    grant_matches: list[GrantMatch] = field(default_factory=list)
    fgac_matches: list[FgacMatch] = field(default_factory=list)
    governed_tags: dict[str, list[str]] = field(
        default_factory=dict
    )  # name → allowed values
    groups: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )  # name → direct members
    service_principals: frozenset[str] = frozenset()  # display names, from the dump
    function_definitions: dict[str, str] = field(
        default_factory=dict
    )  # fn full_name → return expr
    drift: list[GrantDrift] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # member -> transitive groups, built once in __post_init__ from membership_closure
    _groups_by_member: dict[str, frozenset[str]] = field(
        init=False, repr=False, compare=False
    )

    # ---- derived indexes (built once at construction) ----

    def __post_init__(self) -> None:
        """Index each member's transitive groups so lookups do not rescan the closure.

        ``membership_closure`` must not be changed after construction; the index would
        not see the change.
        """
        grouped: dict[str, set[str]] = {}
        for edge in self.membership_closure:
            grouped.setdefault(edge.member, set()).add(edge.group)
        self._groups_by_member = {
            member: frozenset(groups) for member, groups in grouped.items()
        }

    def groups_of(self, principal: str) -> set[str]:
        """All groups a principal belongs to, transitively (a fresh set)."""
        return set(self._groups_by_member.get(principal, frozenset()))

    def principal_matches(self, principal: str, declared: str) -> bool:
        """Whether a policy principal entry covers ``principal``: the all-users
        group, the principal itself, or a group in its closure."""
        if declared == ALL_USERS_GROUP:
            return True
        return declared == principal or declared in self.groups_of(principal)

    def users(self) -> set[str]:
        """Every user/SP discoverable from memberships or policy references."""
        membership_users = {
            e.member for e in self.membership_closure if e.member not in self.groups
        }
        return membership_users | {
            principal
            for principal in self.policy_principals()
            if principal not in self.groups and principal not in SYSTEM_GROUPS
        }

    def policy_principals(self) -> set[str]:
        principals = {
            principal
            for policy in self.grant_policies.values()
            for principal in policy.to
        }
        for policy in self.fgac_policies.values():
            principals.update(policy.to)
            principals.update(policy.exceptions)
        return principals

    def principals(self) -> set[str]:
        """All selectable principals, including referenced system groups."""
        return (
            self.users() | set(self.groups) | (self.policy_principals() & SYSTEM_GROUPS)
        )
