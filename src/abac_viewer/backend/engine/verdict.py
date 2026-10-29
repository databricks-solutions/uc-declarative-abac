"""Verdict + why-chain evaluation over a FactoredModel.

All functions are pure and output-sensitive: they touch only the policies,
grants, and memberships that connect the one principal and securable being
asked about. The chain nodes returned are the join witnesses; there is no
separate explanation machinery.

Verdict semantics (declared intent):
- READ on a table = effective use_catalog on its catalog AND use_schema on its
  schema AND select on the table, each satisfiable at the securable itself or
  any ancestor (UC privilege inheritance).
- A column is MASKED for P iff some matching mask policy lists P in its
  expanded 'to' and not in its expanded 'except'.
- Rows are FILTERED for P analogously via filter policies.
- Ownership, admin roles, and direct (non-policy) grants are out of scope —
  the model contains declared config only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from abac_viewer.backend.engine.model import (
    ALL_USERS_GROUP,
    CompiledFgacPolicy,
    CompiledGrantPolicy,
    FactoredModel,
    FgacMatch,
    GrantMatch,
    MembershipEdge,
)

_READ_PREREQS = ("use_catalog", "use_schema", "select")


@dataclass(frozen=True)
class ChainNode:
    """One typed step in a why-chain. ``kind`` ∈ membership | tag | policy |
    grant | effect. ``source`` is a config file[:line] when known."""

    kind: str
    label: str
    detail: str = ""
    source: str | None = None


@dataclass
class ColumnVerdict:
    column: str
    data_type: str | None
    masked: bool
    mask_policy_ids: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    principal: str
    securable: str
    can_read: bool
    row_filtered: bool
    missing: list[str] = field(default_factory=list)  # unmet read prerequisites
    columns: list[ColumnVerdict] = field(default_factory=list)
    chains: list[list[ChainNode]] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.can_read:
            return "no_access"
        if any(c.masked for c in self.columns):
            return "partial"
        return "filtered" if self.row_filtered else "full"


def _fmt_source(provenance) -> str | None:
    if provenance is None:
        return None
    return (
        f"{provenance.file}:{provenance.line}" if provenance.line else provenance.file
    )


def _membership_witness(
    model: FactoredModel, principal: str, declared: str
) -> MembershipEdge | None:
    """The closure row proving ``principal`` is covered by ``declared`` (None
    when declared is the principal itself or the all-users group)."""
    if declared in (principal, ALL_USERS_GROUP):
        return None
    for edge in model.membership_closure:
        if edge.member == principal and edge.group == declared:
            return edge
    return None


def _covering_entries(
    model: FactoredModel, principal: str, declared: tuple[str, ...]
) -> list[str]:
    return [d for d in declared if model.principal_matches(principal, d)]


def _ancestors_and_self(full_name: str) -> list[str]:
    parts = full_name.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


# The securable types on which ALL PRIVILEGES includes each read prerequisite:
# USE CATALOG only on a catalog, USE SCHEMA on a schema or its catalog, SELECT on a
# table or any ancestor.
_ALL_PRIVILEGES_SCOPE = {
    "use_catalog": frozenset({"catalog"}),
    "use_schema": frozenset({"catalog", "schema"}),
    "select": frozenset({"catalog", "schema", "table"}),
}


def _prerequisites_satisfied_by(gm: GrantMatch) -> tuple[str, ...]:
    """The read prerequisites a grant on the table's path satisfies: its own privilege,
    or for ALL PRIVILEGES those its securable type can carry."""
    if gm.privilege == "all_privileges":
        return tuple(
            p for p in _READ_PREREQS if gm.securable_type in _ALL_PRIVILEGES_SCOPE[p]
        )
    return (gm.privilege,) if gm.privilege in _READ_PREREQS else ()


def _grants_for(
    model: FactoredModel, principal: str, table_full_name: str
) -> dict[str, list[GrantMatch]]:
    """Effective grants toward reading ``table_full_name``: privilege → the
    GrantMatch rows on the table or any ancestor whose principal covers P."""
    scope = set(_ancestors_and_self(table_full_name))
    out: dict[str, list[GrantMatch]] = {p: [] for p in _READ_PREREQS}
    for gm in model.grant_matches:
        if gm.securable_full_name not in scope:
            continue
        if not model.principal_matches(principal, gm.principal):
            continue
        for prerequisite in _prerequisites_satisfied_by(gm):
            out[prerequisite].append(gm)
    return out


def pick_witness(matches: list[GrantMatch], table_full_name: str) -> GrantMatch:
    """The most relevant witness for an explanation about ``table_full_name``:
    prefer a match whose tag-matched securable is the table itself or an
    ancestor of it (deepest first), so e.g. a USE_CATALOG grant emitted by
    many matches is explained via the one on this table's own path rather
    than an unrelated sibling."""

    def score(gm: GrantMatch) -> int:
        matched = gm.matched_securable_full_name or gm.securable_full_name
        if table_full_name == matched or table_full_name.startswith(f"{matched}."):
            return len(matched.split("."))
        return 0

    return max(matches, key=score)


def grant_witnesses(
    matches: list[GrantMatch], table_full_name: str
) -> list[GrantMatch]:
    """Every distinct grant witness anchored on the explained table path.

    Cascaded traversal grants can also be emitted from tag matches on sibling
    securables. Prefer the witnesses whose matched securable is the table or
    one of its ancestors, while retaining parallel policies and principals.
    """
    on_path = [
        match
        for match in matches
        if table_full_name
        == (match.matched_securable_full_name or match.securable_full_name)
        or table_full_name.startswith(
            f"{match.matched_securable_full_name or match.securable_full_name}."
        )
    ]
    return (
        list(dict.fromkeys(on_path))
        if on_path
        else [pick_witness(matches, table_full_name)]
    )


def _membership_node(model: FactoredModel, principal: str, declared: str) -> ChainNode:
    if declared == ALL_USERS_GROUP:
        return ChainNode(
            kind="membership",
            label=f"everyone ({ALL_USERS_GROUP})",
            detail=f"'{declared}' covers every principal",
        )
    if declared == principal:
        return ChainNode(
            kind="membership", label=principal, detail="named directly in the policy"
        )
    edge = _membership_witness(model, principal, declared)
    via = " ⊂ ".join(edge.via) if edge else declared
    return ChainNode(
        kind="membership",
        label=f"{principal} ∈ {declared}",
        detail=f"membership chain: {principal} → {via}",
        source=_fmt_source(edge.provenance) if edge else None,
    )


def _grant_policy_node(policy: CompiledGrantPolicy) -> ChainNode:
    """The chain node for the grant policy behind a grant; a manual grant (a privilege
    no grant policy produces) says so instead of naming a policy."""
    if policy.origin == "direct":
        return ChainNode(
            kind="policy",
            label="manual grant",
            detail="not produced by a grant policy (granted outside the config)",
        )
    return ChainNode(
        kind="policy",
        label=f"grant policy '{policy.name}'",
        detail=f"attached to {policy.parent_full_name}",
        source=_fmt_source(policy.provenance),
    )


def _grant_chain(
    model: FactoredModel, principal: str, gm: GrantMatch
) -> list[ChainNode]:
    policy = model.grant_policies[gm.policy_id]
    nodes = [_membership_node(model, principal, gm.principal)]
    if gm.matched_tags:
        tags = ", ".join(f"{k}={v}" for k, v in gm.matched_tags)
        matched_on = gm.matched_securable_full_name or gm.securable_full_name
        nodes.append(
            ChainNode(
                kind="tag",
                label=f"tags on {matched_on}",
                detail=f"matched: {tags}",
            )
        )
    nodes.append(_grant_policy_node(policy))
    nodes.append(
        ChainNode(
            kind="grant",
            label=f"{gm.privilege.upper()} on {gm.securable_full_name}",
            detail=f"granted to {gm.principal}",
        )
    )
    return nodes


def _fgac_applies_to(
    model: FactoredModel, policy: CompiledFgacPolicy, principal: str
) -> tuple[bool, str | None, str | None]:
    """(applies, covering 'to' entry, covering 'except' entry)."""
    covered_by = next(
        (d for d in policy.to if model.principal_matches(principal, d)), None
    )
    excepted_by = next(
        (d for d in policy.exceptions if model.principal_matches(principal, d)), None
    )
    return (covered_by is not None and excepted_by is None), covered_by, excepted_by


def row_filter_state_details_for(
    model: FactoredModel,
    principal: str,
    table_full_name: str,
    column: str | None = None,
) -> tuple[bool, bool, str | None]:
    """Return (targeted, filtered, excepted_by), optionally for one column."""
    targeted = False
    matched_exception: str | None = None
    for match in model.fgac_matches:
        if match.table_full_name != table_full_name:
            continue
        policy = model.fgac_policies[match.policy_id]
        if policy.policy_type != "filter":
            continue
        if column is not None and not any(
            column_name == column for column_name, _atoms in match.matched_columns
        ):
            continue
        targeted = True
        applies, _covered_by, excepted_by = _fgac_applies_to(
            model,
            policy,
            principal,
        )
        if applies:
            return True, True, None
        if excepted_by is not None and matched_exception is None:
            matched_exception = excepted_by
    return targeted, False, matched_exception


def row_filter_state_for(
    model: FactoredModel,
    principal: str,
    table_full_name: str,
    column: str | None = None,
) -> tuple[bool, bool]:
    """Return (targeted, filtered), optionally scoped to one input column."""
    targeted, filtered, _excepted_by = row_filter_state_details_for(
        model,
        principal,
        table_full_name,
        column,
    )
    return targeted, filtered


def row_filtered_for(
    model: FactoredModel,
    principal: str,
    table_full_name: str,
) -> bool:
    """Whether any matching row-filter policy applies to this principal/table."""
    _targeted, filtered = row_filter_state_for(model, principal, table_full_name)
    return filtered


@dataclass(frozen=True)
class MaskCandidate:
    match: FgacMatch
    policy: CompiledFgacPolicy
    tag_atoms: tuple[tuple[str, str], ...]
    applies: bool
    covered_by: str | None
    excepted_by: str | None


def _select_mask_candidate(
    model: FactoredModel,
    principal: str,
    table_full_name: str,
    column: str,
) -> MaskCandidate | None:
    """Choose the policy that explains a column's effective mask state."""
    candidates: list[MaskCandidate] = []
    for match in model.fgac_matches:
        if match.table_full_name != table_full_name:
            continue
        policy = model.fgac_policies[match.policy_id]
        if policy.policy_type != "mask":
            continue
        tag_atoms = next(
            (atoms for name, atoms in match.matched_columns if name == column),
            None,
        )
        if tag_atoms is None:
            continue
        applies, covered_by, excepted_by = _fgac_applies_to(model, policy, principal)
        candidates.append(
            MaskCandidate(
                match=match,
                policy=policy,
                tag_atoms=tag_atoms,
                applies=applies,
                covered_by=covered_by,
                excepted_by=excepted_by,
            )
        )
    return (
        next((candidate for candidate in candidates if candidate.applies), None)
        or next(
            (
                candidate
                for candidate in candidates
                if candidate.excepted_by is not None
            ),
            None,
        )
        or (candidates[0] if candidates else None)
    )


def _fgac_chain(
    model: FactoredModel,
    principal: str,
    match: FgacMatch,
    covered_by: str,
    effect: str,
) -> list[ChainNode]:
    policy = model.fgac_policies[match.policy_id]
    nodes = [_membership_node(model, principal, covered_by)]
    if match.matched_table_tags:
        tags = ", ".join(f"{k}={v}" for k, v in match.matched_table_tags)
        nodes.append(
            ChainNode(
                kind="tag",
                label=f"tags on {match.table_full_name}",
                detail=f"matched: {tags}",
            )
        )
    nodes.append(
        ChainNode(
            kind="policy",
            label=f"{policy.policy_type} policy '{policy.name}'",
            detail=f"attached to {policy.parent_full_name}, function {policy.function}",
            source=_fmt_source(policy.provenance),
        )
    )
    nodes.append(ChainNode(kind="effect", label=effect))
    return nodes


def evaluate(model: FactoredModel, principal: str, table_full_name: str) -> Verdict:
    """Full verdict + chains for one (principal, table)."""
    grants = _grants_for(model, principal, table_full_name)
    missing = [p for p in _READ_PREREQS if not grants[p]]
    can_read = not missing

    chains: list[list[ChainNode]] = []
    if can_read:
        seen_grants: set[GrantMatch] = set()
        for prereq in _READ_PREREQS:
            for gm in grant_witnesses(grants[prereq], table_full_name):
                if gm not in seen_grants:
                    seen_grants.add(gm)
                    chains.append(_grant_chain(model, principal, gm))

    row_filtered = False
    columns: dict[str, ColumnVerdict] = {}
    for sec in model.securables.values():
        if sec.securable_type == "column" and sec.parent_full_name == table_full_name:
            columns[sec.full_name.rsplit(".", 1)[1]] = ColumnVerdict(
                column=sec.full_name.rsplit(".", 1)[1],
                data_type=sec.data_type,
                masked=False,
            )

    for match in model.fgac_matches:
        if match.table_full_name != table_full_name:
            continue
        policy = model.fgac_policies[match.policy_id]
        applies, covered_by, excepted_by = _fgac_applies_to(model, policy, principal)
        if not applies or covered_by is None:
            if excepted_by is not None and can_read:
                effect = f"EXEMPT from {policy.policy_type} '{policy.name}' via {excepted_by}"
                chains.append(_fgac_chain(model, principal, match, excepted_by, effect))
            continue
        if policy.policy_type == "filter":
            row_filtered = True
            if can_read:
                chains.append(
                    _fgac_chain(
                        model,
                        principal,
                        match,
                        covered_by,
                        f"ROWS FILTERED by {policy.function}",
                    )
                )
        else:
            for col_name, _atoms in match.matched_columns:
                cv = columns.setdefault(
                    col_name,
                    ColumnVerdict(column=col_name, data_type=None, masked=False),
                )
                cv.masked = True
                cv.mask_policy_ids.append(match.policy_id)
            if can_read and match.matched_columns:
                cols = ", ".join(c for c, _ in match.matched_columns)
                chains.append(
                    _fgac_chain(
                        model,
                        principal,
                        match,
                        covered_by,
                        f"MASKED columns [{cols}] by {policy.function}",
                    )
                )

    return Verdict(
        principal=principal,
        securable=table_full_name,
        can_read=can_read,
        row_filtered=row_filtered,
        missing=missing,
        columns=sorted(columns.values(), key=lambda c: c.column),
        chains=chains,
    )


@dataclass
class ChainGroup:
    """One deduplicated reason, mirroring the anchor-model graph: a shared
    header (membership → matched tag → policy) with the effects it produces
    listed underneath. Replaces the old per-privilege chain repetition."""

    membership: ChainNode
    policy: ChainNode
    tag: ChainNode | None
    effects: list[ChainNode] = field(default_factory=list)


def grouped_chains(
    model: FactoredModel, principal: str, table_full_name: str
) -> list[ChainGroup]:
    """Grouped why-detail for a (principal, table): one group per
    (principal-entry, policy, matched-securable), effects collected under it."""
    grants = _grants_for(model, principal, table_full_name)
    if any(not grants[p] for p in _READ_PREREQS):
        return []

    groups: dict[tuple, ChainGroup] = {}

    def group_for(gm: GrantMatch) -> ChainGroup:
        policy = model.grant_policies[gm.policy_id]
        anchor = gm.matched_securable_full_name or gm.securable_full_name
        key = (gm.principal, gm.policy_id, anchor)
        if key not in groups:
            tag_node = None
            if gm.matched_tags:
                tags = ", ".join(f"{k}={v}" for k, v in gm.matched_tags)
                tag_node = ChainNode(
                    kind="tag", label=f"tags on {anchor}", detail=f"matched: {tags}"
                )
            groups[key] = ChainGroup(
                membership=_membership_node(model, principal, gm.principal),
                policy=_grant_policy_node(policy),
                tag=tag_node,
            )
        return groups[key]

    seen_grants: set[GrantMatch] = set()
    for prereq in _READ_PREREQS:
        for gm in grant_witnesses(grants[prereq], table_full_name):
            if gm in seen_grants:
                continue
            seen_grants.add(gm)
            g = group_for(gm)
            g.effects.append(
                ChainNode(
                    kind="grant",
                    label=f"{gm.privilege.upper()} on {gm.securable_full_name}",
                    detail=f"granted to {gm.principal}",
                )
            )

    for match in model.fgac_matches:
        if match.table_full_name != table_full_name:
            continue
        policy = model.fgac_policies[match.policy_id]
        if policy.policy_type != "filter":
            continue
        applies, covered_by, excepted_by = _fgac_applies_to(model, policy, principal)
        declared = covered_by if applies else excepted_by
        if declared is None:
            continue
        key = (declared, policy.policy_id, match.table_full_name)
        if key not in groups:
            tag_node = None
            if match.matched_table_tags:
                tags = ", ".join(f"{k}={v}" for k, v in match.matched_table_tags)
                tag_node = ChainNode(
                    kind="tag",
                    label=f"tags on {match.table_full_name}",
                    detail=f"matched: {tags}",
                )
            groups[key] = ChainGroup(
                membership=_membership_node(model, principal, declared),
                policy=ChainNode(
                    kind="policy",
                    label=f"filter policy '{policy.name}'",
                    detail=(
                        f"attached to {policy.parent_full_name}, "
                        f"function {policy.function}"
                    ),
                    source=_fmt_source(policy.provenance),
                ),
                tag=tag_node,
            )
        groups[key].effects.append(
            ChainNode(
                kind="effect",
                label=(
                    f"ROWS FILTERED by {policy.function}"
                    if applies
                    else f"EXEMPT from filter '{policy.name}' via {excepted_by}"
                ),
            )
        )
    return list(groups.values())


@dataclass(frozen=True)
class PolicyArgumentExplanation:
    position: int
    kind: str
    alias: str | None
    constant: bool | int | float | str | None
    constant_type: str | None
    target: bool
    matched_columns: tuple[str, ...]


@dataclass
class ColumnMaskExplanation:
    """Why one column is (or isn't) masked for a principal — the mask flow
    only. Table read-access is a separate concern (the table verdict)."""

    principal: str
    column_full_name: str
    table_full_name: str
    column: str
    data_type: str | None
    can_read_table: bool
    masked: bool
    # the mask/exempt policy that decides it, if any
    policy_id: str | None = None
    policy_name: str | None = None
    function: str | None = None
    covered_by: str | None = None  # 'to' entry matching the principal
    excepted_by: str | None = None  # 'except' entry matching the principal
    tag_atoms: tuple[tuple[str, str], ...] = ()  # column tags that matched
    # where the deciding policy is attached (the securable whose `policies:`
    # list declares it — e.g. the catalog) and its level + config source.
    policy_attached_to: str | None = None
    policy_attached_level: str | None = None  # catalog | schema | table
    policy_source: str | None = None  # "file:line" for GitHub deep-link
    arguments: tuple[PolicyArgumentExplanation, ...] = ()
    sentence: str = ""


def _column_tags(model: FactoredModel, column_full_name: str) -> dict[str, str]:
    return {
        t.tag_name: t.tag_value
        for t in model.tag_assignments
        if t.securable_full_name == column_full_name
    }


def _column_sentence(exp: ColumnMaskExplanation) -> str:
    who = exp.principal
    col = exp.column_full_name
    if exp.policy_id is None:
        return f"{who} sees {col} unmasked — no mask policy targets this column."
    tags = ", ".join(f"{k}={v}" for k, v in exp.tag_atoms) or "a tag"
    if exp.masked:
        return (
            f"{who} sees {col} MASKED by {exp.function} — column tagged {tags} "
            f"matches mask policy '{exp.policy_name}', and {who} is covered by "
            f"its 'to' ({exp.covered_by})."
        )
    if exp.excepted_by is not None:
        return (
            f"{who} sees {col} unmasked — mask policy '{exp.policy_name}' targets "
            f"tag {tags}, but {who} is exempt via 'except' ({exp.excepted_by})."
        )
    return (
        f"{who} sees {col} unmasked — mask policy '{exp.policy_name}' targets tag "
        f"{tags}, but {who} is not in its 'to' list."
    )


def evaluate_column(
    model: FactoredModel,
    principal: str,
    column_full_name: str,
    can_read_table: bool | None = None,
) -> ColumnMaskExplanation:
    """Mask verdict + the deciding policy for one (principal, column)."""
    table_full_name = column_full_name.rsplit(".", 1)[0]
    col_name = column_full_name.rsplit(".", 1)[1]
    sec = model.securables.get(column_full_name)
    data_type = sec.data_type if sec else None
    if can_read_table is None:
        grants = _grants_for(model, principal, table_full_name)
        can_read_table = not [p for p in _READ_PREREQS if not grants[p]]

    exp = ColumnMaskExplanation(
        principal=principal,
        column_full_name=column_full_name,
        table_full_name=table_full_name,
        column=col_name,
        data_type=data_type,
        can_read_table=can_read_table,
        masked=False,
    )

    candidate = _select_mask_candidate(model, principal, table_full_name, col_name)
    if candidate is not None:
        policy = candidate.policy
        exp.policy_id = policy.policy_id
        exp.policy_name = policy.name
        exp.function = policy.function
        exp.covered_by = candidate.covered_by
        exp.excepted_by = candidate.excepted_by
        exp.tag_atoms = candidate.tag_atoms
        exp.masked = candidate.applies
        matches_by_alias = {
            alias: tuple(column for column, _atoms in matches)
            for alias, matches in candidate.match.matched_aliases
        }
        exp.arguments = tuple(
            PolicyArgumentExplanation(
                position=position,
                kind=argument.kind,
                alias=argument.alias,
                constant=argument.constant,
                constant_type=argument.constant_type,
                target=position == 1,
                matched_columns=(
                    (col_name,)
                    if position == 1
                    else matches_by_alias.get(argument.alias or "", ())
                ),
            )
            for position, argument in enumerate(policy.column_arguments, start=1)
        )
        # where the policy is *applied* (its `policies:` attachment point) — the
        # catalog for a catalog-level policy like mask_pii_contact. Link to that
        # securable's config (e.g. abac_viz_demo.yaml), not the policy definition.
        exp.policy_attached_to = policy.parent_full_name
        parent = model.securables.get(policy.parent_full_name)
        exp.policy_attached_level = parent.securable_type if parent else None
        prov = parent.provenance if parent else policy.provenance
        if prov is not None:
            exp.policy_source = f"{prov.file}:{prov.line}" if prov.line else prov.file

    exp.sentence = _column_sentence(exp)
    return exp


def masked_columns_for(
    model: FactoredModel, principal: str
) -> list[ColumnMaskExplanation]:
    """Every column the principal can reach, with its mask verdict. Filtering
    (all/masked/unmasked) is left to the caller."""
    out: list[ColumnMaskExplanation] = []
    columns_by_table: dict[str, list[str]] = {}
    for sec in model.securables.values():
        if sec.securable_type == "column" and sec.parent_full_name is not None:
            columns_by_table.setdefault(sec.parent_full_name, []).append(sec.full_name)
    for table_full_name in sorted(columns_by_table):
        grants = _grants_for(model, principal, table_full_name)
        if any(not grants[prereq] for prereq in _READ_PREREQS):
            continue
        for column_full_name in sorted(columns_by_table[table_full_name]):
            exp = evaluate_column(
                model,
                principal,
                column_full_name,
                can_read_table=True,
            )
            out.append(exp)
    return out


def readable_tables(model: FactoredModel, principal: str) -> list[Verdict]:
    """Verdicts for every table (output-sensitive per-table evaluation)."""
    return [
        evaluate(model, principal, sec.full_name)
        for sec in sorted(model.securables.values(), key=lambda s: s.full_name)
        if sec.securable_type == "table"
    ]


def who_can_read(model: FactoredModel, table_full_name: str) -> list[Verdict]:
    """Verdicts for every known leaf principal against one table."""
    principals = sorted(model.users() | set(model.groups))
    return [
        v
        for v in (evaluate(model, p, table_full_name) for p in principals)
        if v.can_read
    ]


def explanation_sentence(verdict: Verdict) -> str:
    """The NL banner for the trace graph, e.g. the deck's Alice Chen sentence."""
    if not verdict.can_read:
        return (
            f"{verdict.principal} cannot read {verdict.securable} — "
            f"missing {', '.join(verdict.missing)}."
        )
    masked = [c.column for c in verdict.columns if c.masked]
    parts = [f"{verdict.principal} can read {verdict.securable}"]
    if masked:
        parts.append(f"with columns [{', '.join(masked)}] masked")
    if verdict.row_filtered:
        parts.append("with rows filtered")
    vias = []
    for chain in verdict.chains:
        grant = next((n for n in chain if n.kind == "grant"), None)
        member = next((n for n in chain if n.kind == "membership"), None)
        if grant and member:
            vias.append(f"{grant.label} via {member.label}")
    if vias:
        parts.append("— " + "; ".join(dict.fromkeys(vias)))
    return " ".join(parts) + "."
