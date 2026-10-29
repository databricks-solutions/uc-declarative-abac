"""Why-chain graph: the deck's full privilege chain as nodes + edges.

user/SP → subgroup → … → group → policy → tag → securable, including the
securable containment chain (catalog ⊃ schema ⊃ table ⊃ column) so cascaded
grants (use_catalog landing on the catalog) and inheritance are visible.

Layers (left→right): 0 = principal; 1..G = groups by depth in the membership
chain; G+1 = policies; G+2 = tags; G+3 = securables (hierarchy edges run
within the layer).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from abac_viewer.backend.engine.model import (
    ALL_USERS_GROUP,
    CompiledFgacPolicy,
    FactoredModel,
    FgacMatch,
)
from abac_viewer.backend.engine.verdict import (
    _READ_PREREQS,
    _fgac_applies_to,
    _grants_for,
    _membership_witness,
    _select_mask_candidate,
    grant_witnesses,
)


@dataclass(frozen=True)
class GNode:
    id: str
    kind: str  # user | group | policy | tag | securable | column
    label: str
    layer: int
    sublabel: str = ""
    source: str | None = None  # display string "file:line"
    source_file: str | None = None  # config-relative path, for GitHub links
    source_line: int | None = None


@dataclass(frozen=True)
class GEdge:
    source: str
    target: str
    label: str
    # member | to | matches | tagged | grant | effect | contains
    # | cascade (traverse grant radiating up from the tag-matched securable)
    # | inherit (privilege inherited down from the tag-matched securable)
    # | argument (function using-column or constant)
    kind: str
    source_file: str | None = None
    source_line: int | None = None
    source_securable: str | None = None
    source_securable_type: str | None = None


@dataclass
class ChainGraph:
    principal: str
    securable: str
    nodes: list[GNode] = field(default_factory=list)
    edges: list[GEdge] = field(default_factory=list)


def _fmt_source(provenance) -> str | None:
    if provenance is None:
        return None
    return (
        f"{provenance.file}:{provenance.line}" if provenance.line else provenance.file
    )


def _prov(provenance) -> dict:
    """GNode source fields (display string + raw file/line for GitHub links)."""
    if provenance is None:
        return {"source": None, "source_file": None, "source_line": None}
    return {
        "source": _fmt_source(provenance),
        "source_file": provenance.file,
        "source_line": provenance.line,
    }


def _edge_prov(provenance, securable: str, securable_type: str) -> dict:
    if provenance is None:
        return {}
    return {
        "source_file": provenance.file,
        "source_line": provenance.line,
        "source_securable": securable,
        "source_securable_type": securable_type,
    }


class _Builder:
    def __init__(self, model: FactoredModel, principal: str, table: str):
        self.model = model
        self.principal = principal
        self.table = table
        self.nodes: dict[str, GNode] = {}
        self.edges: set[GEdge] = set()
        self.max_group_layer = 1

    def node(self, node: GNode) -> None:
        existing = self.nodes.get(node.id)
        # keep the deepest layer so shared nodes sit in a consistent column
        if existing is None or node.layer > existing.layer:
            self.nodes[node.id] = node

    def edge(self, e: GEdge) -> None:
        self.edges.add(e)

    # --- membership path: principal → subgroup → … → covering group --------

    def membership_path(self, declared: str) -> str:
        """Add nodes/edges for how the principal is covered by ``declared``;
        returns the node id that should connect to the policy."""
        if declared == self.principal:
            return self.principal
        if declared == ALL_USERS_GROUP:
            self.node(
                GNode(
                    id=declared,
                    kind="group",
                    label="account users",
                    sublabel="everyone",
                    layer=1,
                )
            )
            self.edge(GEdge(self.principal, declared, "member (implicit)", "member"))
            return declared
        witness = _membership_witness(self.model, self.principal, declared)
        if witness is None:
            return self.principal
        prev = self.principal
        for depth, group in enumerate(witness.via, start=1):
            self.max_group_layer = max(self.max_group_layer, depth)
            self.node(
                GNode(
                    id=group,
                    kind="group",
                    label=group,
                    layer=depth,
                    sublabel="subgroup" if depth < len(witness.via) else "",
                    **_prov(witness.provenance),
                )
            )
            self.edge(GEdge(prev, group, "member", "member"))
            prev = group
        return witness.via[-1]


def _constant_label(value, constant_type: str | None) -> str:
    if constant_type == "string":
        return repr(value)
    if constant_type == "bool":
        return str(value).lower()
    return str(value)


def _add_fgac_arguments(
    builder: _Builder,
    model: FactoredModel,
    policy: CompiledFgacPolicy,
    match: FgacMatch,
    table: str,
    tag_layer: int,
    column_layer: int,
    include_contains: bool,
    focused_column: str | None = None,
) -> None:
    matches_by_alias = dict(match.matched_aliases)
    for position, argument in enumerate(policy.column_arguments, start=1):
        if argument.kind == "constant":
            constant_id = f"constant:{policy.policy_id}:{position}"
            builder.node(
                GNode(
                    id=constant_id,
                    kind="constant",
                    label=_constant_label(argument.constant, argument.constant_type),
                    sublabel=f"{argument.constant_type} constant · arg {position}",
                    layer=column_layer,
                )
            )
            builder.edge(
                GEdge(policy.policy_id, constant_id, f"USES ARG {position}", "argument")
            )
            continue

        argument_matches = matches_by_alias.get(argument.alias or "", ())
        if policy.policy_type == "mask" and position == 1 and focused_column:
            argument_matches = tuple(
                match for match in argument_matches if match[0] == focused_column
            )
        for column_name, tag_atoms in argument_matches:
            column_id = f"{table}.{column_name}"
            column = model.securables.get(column_id)
            builder.node(
                GNode(
                    id=column_id,
                    kind="column",
                    label=column_name,
                    sublabel="column",
                    layer=column_layer,
                    **(_prov(column.provenance) if column else _prov(None)),
                )
            )
            if include_contains:
                builder.edge(GEdge(table, column_id, "contains", "contains"))
            for tag_name, tag_value in tag_atoms:
                tag_id = f"tag:{tag_name}={tag_value}"
                builder.node(
                    GNode(
                        id=tag_id,
                        kind="tag",
                        label=f"{tag_name}={tag_value}",
                        sublabel="tag",
                        layer=tag_layer,
                    )
                )
                builder.edge(GEdge(policy.policy_id, tag_id, "matches", "matches"))
                assignment = next(
                    (
                        candidate
                        for candidate in model.tag_assignments
                        if candidate.securable_full_name == column_id
                        and candidate.tag_name == tag_name
                        and candidate.tag_value == tag_value
                    ),
                    None,
                )
                builder.edge(
                    GEdge(
                        tag_id,
                        column_id,
                        "tagged on",
                        "tagged",
                        **_edge_prov(
                            assignment.provenance if assignment else None,
                            column_id,
                            "column",
                        ),
                    )
                )
            is_mask_target = policy.policy_type == "mask" and position == 1
            if not is_mask_target:
                builder.edge(
                    GEdge(
                        policy.policy_id,
                        column_id,
                        f"USES {argument.alias}",
                        "argument",
                    )
                )


def build_chain_graph(
    model: FactoredModel,
    principal: str,
    table: str,
    include_column_masks: bool = True,
    include_row_filters: bool = True,
    include_grants: bool = True,
    focus_column: str | None = None,
) -> ChainGraph:
    """Table access chain graph. ``include_column_masks=False`` omits the whole
    column-mask branch (mask policies, their pii tags, and column nodes) —
    per-column mask detail lives on the column Why page — while keeping
    row-filter effects, which are table-level."""
    b = _Builder(model, principal, table)
    b.node(GNode(id=principal, kind="user", label=principal, sublabel="user", layer=0))
    focused_filter_flow = (
        focus_column is not None and not include_column_masks and not include_grants
    )

    grant_hits: list = []
    if include_grants:
        grants = _grants_for(model, principal, table)
        for prereq in _READ_PREREQS:
            if grants[prereq]:
                grant_hits.extend(grant_witnesses(grants[prereq], table))
        grant_hits = list(dict.fromkeys(grant_hits))

    fgac_hits = []
    for match in model.fgac_matches:
        if match.table_full_name != table:
            continue
        policy = model.fgac_policies[match.policy_id]
        if not include_column_masks and policy.policy_type == "mask":
            continue
        if not include_row_filters and policy.policy_type == "filter":
            continue
        if (
            policy.policy_type == "filter"
            and focus_column is not None
            and not any(
                column_name == focus_column
                for column_name, _atoms in match.matched_columns
            )
        ):
            continue
        applies, covered_by, excepted_by = _fgac_applies_to(model, policy, principal)
        if applies and covered_by is not None:
            fgac_hits.append((match, policy, covered_by, False))
        elif excepted_by is not None:
            fgac_hits.append((match, policy, excepted_by, True))

    # membership layers first so policy/tag layers land after the deepest group
    connectors: dict[tuple[str, str], str] = {}
    for gm in grant_hits:
        connectors[(gm.policy_id, gm.principal)] = b.membership_path(gm.principal)
    for match, policy, covered_by, _ in fgac_hits:
        connectors[(policy.policy_id, covered_by)] = b.membership_path(covered_by)

    policy_layer = b.max_group_layer + 1
    tag_layer = policy_layer + 1
    securable_layer = tag_layer + 1

    def add_securable(full_name: str) -> None:
        sec = model.securables.get(full_name)
        kind = sec.securable_type if sec else "table"
        b.node(
            GNode(
                id=full_name,
                kind="securable",
                label=full_name.rsplit(".", 1)[-1] if "." in full_name else full_name,
                sublabel=kind,
                layer=securable_layer,
                **(_prov(sec.provenance) if sec else _prov(None)),
            )
        )

    if not focused_filter_flow:
        add_securable(table)
    if not include_grants and include_row_filters and not fgac_hits:
        b.edge(GEdge(principal, table, "NO ROW FILTER", "effect"))

    def add_tag_atoms(
        policy_id: str, matched_tags, on_securable: str, grant_label: str = "tagged on"
    ) -> None:
        for tag_name, tag_value in matched_tags:
            tag_id = f"tag:{tag_name}={tag_value}"
            b.node(
                GNode(
                    id=tag_id,
                    kind="tag",
                    label=f"{tag_name}={tag_value}",
                    sublabel="tag",
                    layer=tag_layer,
                )
            )
            b.edge(GEdge(policy_id, tag_id, "matches", "matches"))
            add_securable(on_securable)
            # The tag→securable edge doubles as the grant edge: the policy
            # reaches the securable via the tag, so we label it with the
            # privileges granted there rather than drawing a second, redundant
            # policy→securable line.
            assignment = next(
                (
                    candidate
                    for candidate in model.tag_assignments
                    if candidate.securable_full_name == on_securable
                    and candidate.tag_name == tag_name
                    and candidate.tag_value == tag_value
                ),
                None,
            )
            securable = model.securables.get(on_securable)
            b.edge(
                GEdge(
                    tag_id,
                    on_securable,
                    grant_label,
                    "tagged",
                    **_edge_prov(
                        assignment.provenance if assignment else None,
                        on_securable,
                        securable.securable_type if securable else "securable",
                    ),
                )
            )

    # Grant edges use the anchor model: one solid edge from the policy to the
    # securable where its tag matched (the anchor), labeled with the
    # privileges granted there; effects radiate from the anchor as dotted
    # arrows — traverse grants cascade UP to ancestors, data privileges are
    # inherited DOWN to the explained table.
    by_policy_anchor: dict[tuple[str, str], list] = {}
    for gm in grant_hits:
        anchor = gm.matched_securable_full_name or gm.securable_full_name
        by_policy_anchor.setdefault((gm.policy_id, anchor), []).append(gm)

    for (policy_id, anchor), gms in by_policy_anchor.items():
        policy = model.grant_policies[policy_id]
        b.node(
            GNode(
                id=policy_id,
                kind="policy",
                label=policy.name,
                sublabel="manual grant"
                if policy.origin == "direct"
                else "grant policy",
                layer=policy_layer,
                **_prov(policy.provenance),
            )
        )
        for connector in {connectors[(gm.policy_id, gm.principal)] for gm in gms}:
            b.edge(GEdge(connector, policy_id, "in 'to'", "to"))
        add_securable(anchor)

        at_anchor = sorted(
            {gm.privilege for gm in gms if gm.securable_full_name == anchor}
        )
        grant_label = ", ".join(p.upper() for p in at_anchor) if at_anchor else "grants"
        if gms[0].matched_tags:
            # tag-matched grant: fold the privilege into the tag→securable edge
            # so there's no separate (redundant) policy→securable line.
            add_tag_atoms(policy_id, gms[0].matched_tags, anchor, grant_label)
        else:
            # tagless direct grant: the policy attaches straight to the anchor.
            b.edge(GEdge(policy_id, anchor, grant_label, "grant"))
        for gm in gms:
            if gm.securable_full_name != anchor:
                add_securable(gm.securable_full_name)
                b.edge(
                    GEdge(
                        anchor, gm.securable_full_name, gm.privilege.upper(), "cascade"
                    )
                )
        data_privs = sorted(
            {
                gm.privilege
                for gm in gms
                if gm.securable_full_name == anchor
                and not gm.privilege.startswith("use_")
            }
        )
        if anchor != table and table.startswith(f"{anchor}.") and data_privs:
            b.edge(
                GEdge(
                    anchor,
                    table,
                    f"inherits {', '.join(p.upper() for p in data_privs)}",
                    "inherit",
                )
            )

    for match, policy, covered_by, excepted in fgac_hits:
        b.node(
            GNode(
                id=policy.policy_id,
                kind="policy",
                label=policy.name,
                sublabel=f"{policy.policy_type} policy",
                layer=policy_layer,
                **_prov(policy.provenance),
            )
        )
        edge_label = "in 'except' (exempt)" if excepted else "in 'to'"
        b.edge(
            GEdge(
                connectors[(policy.policy_id, covered_by)],
                policy.policy_id,
                edge_label,
                "to",
            )
        )
        if not focused_filter_flow:
            add_tag_atoms(policy.policy_id, match.matched_table_tags, table)
        _add_fgac_arguments(
            b,
            model,
            policy,
            match,
            table,
            tag_layer,
            securable_layer,
            include_contains=not focused_filter_flow,
        )
        if policy.policy_type == "filter":
            # A row filter matches the table via the tag on its predicate column
            # (e.g. region tagged abac_demo_filter_col); draw policy →matches→ tag
            # →tagged on→ column so the match route is explicit, then the
            # FILTERS ROWS effect on the table (row filtering is table-level).
            if not focused_filter_flow:
                b.edge(
                    GEdge(
                        policy.policy_id,
                        table,
                        "EXEMPT (rows)" if excepted else "FILTERS ROWS",
                        "effect",
                    )
                )
        else:
            for col_name, col_atoms in match.matched_columns:
                col_id = f"{table}.{col_name}"
                b.edge(
                    GEdge(
                        policy.policy_id,
                        col_id,
                        "EXEMPT (mask)" if excepted else "MASKS",
                        "effect",
                    )
                )

    return ChainGraph(
        principal=principal,
        securable=table,
        nodes=sorted(b.nodes.values(), key=lambda n: (n.layer, n.kind, n.id)),
        edges=sorted(b.edges, key=lambda e: (e.source, e.target, e.label)),
    )


def _finish(b: _Builder, principal: str, securable: str) -> ChainGraph:
    return ChainGraph(
        principal=principal,
        securable=securable,
        nodes=sorted(b.nodes.values(), key=lambda n: (n.layer, n.kind, n.id)),
        edges=sorted(b.edges, key=lambda e: (e.source, e.target, e.label)),
    )


def build_column_chain_graph(
    model: FactoredModel, principal: str, column_full_name: str
) -> ChainGraph:
    """Column-scoped mask flow: principal → subgroup → group → mask policy →
    tag → column. Deliberately excludes the table read-access grant chain (a
    separate concern). The graph retains function-argument and effect edges so
    detailed callers can use them; the simplified UI hides those direct edges.

    Only the deciding mask policy is drawn. If the principal is exempt (or not
    in 'to'), the effect edge says so rather than MASKS.
    """
    b = _Builder(model, principal, column_full_name)
    table = column_full_name.rsplit(".", 1)[0]
    col_name = column_full_name.rsplit(".", 1)[1]
    b.node(GNode(id=principal, kind="user", label=principal, sublabel="user", layer=0))

    exp = _select_mask_candidate(model, principal, table, col_name)

    if exp is None:
        # no mask targets this column: principal → column, unmasked
        sec = model.securables.get(column_full_name)
        b.node(
            GNode(
                id=column_full_name,
                kind="column",
                label=col_name,
                sublabel="column · unmasked",
                layer=b.max_group_layer + 3,
                **(_prov(sec.provenance) if sec else _prov(None)),
            )
        )
        b.edge(GEdge(principal, column_full_name, "no mask applies", "effect"))
        return _finish(b, principal, column_full_name)

    policy = exp.policy
    applies = exp.applies
    covered_by = exp.covered_by
    excepted_by = exp.excepted_by
    connector_entry = (
        excepted_by if excepted_by is not None and not applies else covered_by
    )
    connector = b.membership_path(connector_entry or principal)

    policy_layer = b.max_group_layer + 1
    tag_layer = policy_layer + 1
    col_layer = tag_layer + 1

    b.node(
        GNode(
            id=policy.policy_id,
            kind="policy",
            label=policy.name,
            sublabel="mask policy",
            layer=policy_layer,
            **_prov(policy.provenance),
        )
    )
    excepted = excepted_by is not None and not applies
    to_label = (
        "in 'except' (exempt)"
        if excepted
        else ("in 'to'" if covered_by is not None else "not in 'to'")
    )
    b.edge(GEdge(connector, policy.policy_id, to_label, "to"))

    sec = model.securables.get(column_full_name)
    b.node(
        GNode(
            id=column_full_name,
            kind="column",
            label=col_name,
            sublabel=f"column · {'masked' if applies else 'unmasked'}",
            layer=col_layer,
            **(_prov(sec.provenance) if sec else _prov(None)),
        )
    )

    _add_fgac_arguments(
        b,
        model,
        policy,
        exp.match,
        table,
        tag_layer,
        col_layer,
        include_contains=False,
        focused_column=col_name,
    )

    b.edge(
        GEdge(
            policy.policy_id,
            column_full_name,
            "EXEMPT (mask)" if excepted else ("MASKS" if applies else "not in 'to'"),
            "effect",
        )
    )
    return _finish(b, principal, column_full_name)
