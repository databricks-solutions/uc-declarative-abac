from typing import Literal

from databricks.sdk.service.iam import User as UserOut
from fastapi import HTTPException

from .core import Dependencies, create_router
from .engine import (
    ALL_USERS_GROUP,
    BuildInfo,
    BuildInfoDependency,
    FactoredModel,
    ModelDependency,
    ModelStoreDependency,
    ModelUnavailableError,
    build_chain_graph,
    build_column_chain_graph,
    evaluate,
    evaluate_column,
    explanation_sentence,
    grouped_chains,
    masked_columns_for,
    readable_tables,
    row_filter_state_details_for,
    row_filter_state_for,
)
from .models import (
    AccessRowOut,
    ChainGraphEdgeOut,
    ChainGraphNodeOut,
    ChainGraphOut,
    ChainGroupOut,
    ChainNodeOut,
    ColumnAccessRowOut,
    ColumnExplanationOut,
    ColumnPolicyOut,
    ColumnVerdictOut,
    DriftOut,
    GraphEdgeOut,
    GraphNodeOut,
    GraphOut,
    GraphSourceOut,
    InverseGraphOut,
    MetaOut,
    PolicyArgumentOut,
    PrincipalEffectOut,
    PrincipalOut,
    TreeNodeOut,
    VerdictOut,
    VersionOut,
    WhoAmIOut,
)

router = create_router()


@router.get("/version", response_model=VersionOut, operation_id="version")
async def version():
    return VersionOut.from_metadata()


@router.get("/current-user", response_model=UserOut, operation_id="currentUser")
def me(user_ws: Dependencies.UserClient):
    return user_ws.current_user.me()


# --- helpers -------------------------------------------------------------------


def _node_out(n) -> ChainNodeOut:
    return ChainNodeOut(**vars(n))


def _group_out(g) -> ChainGroupOut:
    return ChainGroupOut(
        membership=_node_out(g.membership),
        policy=_node_out(g.policy),
        tag=_node_out(g.tag) if g.tag else None,
        effects=[_node_out(e) for e in g.effects],
    )


def _verdict_out(model: FactoredModel, principal: str, table: str) -> VerdictOut:
    v = evaluate(model, principal, table)
    row_filter_targeted, _row_filtered, row_filter_excepted_by = (
        row_filter_state_details_for(model, principal, table)
    )
    return VerdictOut(
        principal=v.principal,
        securable=v.securable,
        status=v.status,
        can_read=v.can_read,
        row_filter_targeted=row_filter_targeted,
        row_filtered=v.row_filtered,
        row_filter_excepted_by=row_filter_excepted_by,
        missing=v.missing,
        columns=[ColumnVerdictOut(**vars(c)) for c in v.columns],
        chains=[[ChainNodeOut(**vars(n)) for n in chain] for chain in v.chains],
        groups=[_group_out(g) for g in grouped_chains(model, principal, table)],
        sentence=explanation_sentence(v),
    )


def _tags_of(model: FactoredModel, full_name: str) -> dict[str, str]:
    return {
        t.tag_name: t.tag_value
        for t in model.tag_assignments
        if t.securable_full_name == full_name
    }


def _validate_column(model: FactoredModel, column: str) -> None:
    parts = column.split(".")
    if len(parts) != 4 or any(not part for part in parts):
        raise HTTPException(
            status_code=422,
            detail="column must be catalog.schema.table.column",
        )
    securable = model.securables.get(column)
    if securable is None or securable.securable_type != "column":
        raise HTTPException(status_code=404, detail=f"column not found: {column}")


# --- identity + inventory --------------------------------------------------------


@router.get("/whoami", response_model=WhoAmIOut, operation_id="whoami")
def whoami(
    headers: Dependencies.Headers,
    user_ws: Dependencies.UserClient,
    model: ModelDependency,
):
    principal = headers.user_email or headers.user_name
    if principal is None:
        current = user_ws.current_user.me()
        principal = current.user_name or current.display_name
    if principal is None:
        raise HTTPException(status_code=503, detail="current user identity unavailable")
    groups = sorted(model.groups_of(principal))
    known = principal in model.principals()
    return WhoAmIOut(principal=principal, known=known, groups=groups)


@router.get(
    "/principals", response_model=list[PrincipalOut], operation_id="listPrincipals"
)
def list_principals(model: ModelDependency):
    out = [
        PrincipalOut(
            name=u,
            kind="service_principal" if u in model.service_principals else "user",
            groups=sorted(model.groups_of(u)),
        )
        for u in sorted(model.users())
        if u != "anonymous"
    ]
    group_names = set(model.groups) | (model.policy_principals() - model.users())
    out += [
        PrincipalOut(name=g, kind="group", groups=sorted(model.groups_of(g)))
        for g in sorted(group_names)
        if g != "anonymous"
    ]
    return out


def _uc_privilege(privilege: str) -> str:
    """UC spelling of an engine privilege, e.g. ``use_schema`` -> ``USE SCHEMA``."""
    return privilege.upper().replace("_", " ")


_READ_PREREQUISITES = ("use_catalog", "use_schema")


def _grant_edge_label(privileges: set[str]) -> str:
    """The label of a grant edge into a table: the privileges it grants other than
    USE CATALOG and USE SCHEMA, or, for a grant that only supplies those read
    prerequisites, the prerequisites themselves (catalog first)."""
    own = sorted(_uc_privilege(p) for p in privileges if p not in _READ_PREREQUISITES)
    if own:
        return ", ".join(own)
    return ", ".join(_uc_privilege(p) for p in _READ_PREREQUISITES if p in privileges)


def _drift_out(model: FactoredModel, drift) -> DriftOut:
    return DriftOut(
        policy_id=drift.policy_id,
        policy_name=model.grant_policies[drift.policy_id].name,
        principal=drift.principal,
        securable=drift.securable_full_name,
        securable_type=drift.securable_type,
        privilege=_uc_privilege(drift.privilege),
    )


def _meta_out(model: FactoredModel, build: BuildInfo) -> MetaOut:
    return MetaOut(
        revision=model.revision,
        source=model.source,
        securables=len(model.securables),
        tables=sum(1 for s in model.securables.values() if s.securable_type == "table"),
        principals=len(model.principals()),
        policies=len(model.grant_policies) + len(model.fgac_policies),
        warnings=model.warnings,
        drift=[_drift_out(model, d) for d in model.drift],
        build_sha=build.sha,
        repo_slug=build.repo_slug,
        config_path_prefix=build.config_path_prefix,
    )


@router.get("/meta", response_model=MetaOut, operation_id="meta")
def meta(model: ModelDependency, build: BuildInfoDependency):
    return _meta_out(model, build)


@router.post("/refresh", response_model=MetaOut, operation_id="refresh")
def refresh(store: ModelStoreDependency, build: BuildInfoDependency):
    """Reload the model from the dump tables; 503 with the reason when that fails (the
    previously loaded model, if any, keeps being served)."""
    try:
        model = store.refresh()
    except ModelUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return _meta_out(model, build)


@router.get("/tables", response_model=list[str], operation_id="listTables")
def list_tables(model: ModelDependency):
    return sorted(
        s.full_name for s in model.securables.values() if s.securable_type == "table"
    )


def _column_policy_index(
    model,
) -> dict[str, dict[str, set[str]]]:
    index: dict[str, dict[str, set[str]]] = {}
    for match in model.fgac_matches:
        policy = model.fgac_policies[match.policy_id]
        for column, _atoms in match.matched_columns:
            column_full_name = f"{match.table_full_name}.{column}"
            effects = index.setdefault(
                column_full_name,
                {"mask": set(), "filter": set()},
            )
            effects[policy.policy_type].add(policy.policy_id)
    return index


@router.get("/tree", response_model=list[TreeNodeOut], operation_id="securableTree")
def securable_tree(model: ModelDependency, principal: str | None = None):
    """Catalog → schema → table hierarchy (UC Catalog-Explorer style). When a
    principal is given, table nodes carry a read/masked rollup for it.

    Row-filter targeting is principal-independent, so table nodes carry it in the
    inventory (All Principals) tree too; a principal's verdict then replaces it.
    """
    # index children by parent
    by_parent: dict[str | None, list] = {}
    for s in model.securables.values():
        if s.securable_type in ("catalog", "schema", "table"):
            by_parent.setdefault(s.parent_full_name, []).append(s)

    # precompute per-table rollup for the principal
    table_stats: dict[str, tuple[bool, bool, bool, int, int, int]] = {}
    policy_index = _column_policy_index(model)
    filter_policy_ids_by_table: dict[str, set[str]] = {}
    for match in model.fgac_matches:
        if model.fgac_policies[match.policy_id].policy_type == "filter":
            filter_policy_ids_by_table.setdefault(match.table_full_name, set()).add(
                match.policy_id
            )
    if principal:
        for v in readable_tables(model, principal):
            masked = sum(1 for c in v.columns if c.masked)
            mask_targeted = sum(
                1
                for column in v.columns
                if policy_index.get(f"{v.securable}.{column.column}", {}).get("mask")
            )
            row_filter_targeted, _row_filtered = row_filter_state_for(
                model, principal, v.securable
            )
            table_stats[v.securable] = (
                v.can_read,
                v.row_filtered,
                row_filter_targeted,
                masked,
                mask_targeted,
                len(v.columns),
            )

    def build(full_name: str, sec) -> TreeNodeOut:
        node = TreeNodeOut(
            full_name=full_name,
            name=full_name.rsplit(".", 1)[-1] if "." in full_name else full_name,
            securable_type=sec.securable_type,
        )
        if sec.securable_type == "table":
            # principal-independent targeting (see docstring)
            node.row_filter_targeted = bool(filter_policy_ids_by_table.get(full_name))
            if principal and full_name in table_stats:
                (
                    can_read,
                    row_filtered,
                    row_filter_targeted,
                    masked,
                    mask_targeted,
                    cols,
                ) = table_stats[full_name]
                node.readable = can_read
                node.row_filtered = row_filtered
                node.row_filter_targeted = row_filter_targeted
                node.masked_column_count = masked
                node.mask_policy_column_count = mask_targeted
                node.column_count = cols
        else:
            node.children = [
                build(c.full_name, c)
                for c in sorted(by_parent.get(full_name, []), key=lambda x: x.full_name)
            ]
        return node

    roots = sorted(
        (s for s in model.securables.values() if s.securable_type == "catalog"),
        key=lambda x: x.full_name,
    )
    return [build(r.full_name, r) for r in roots]


@router.get("/column-names", response_model=list[str], operation_id="listColumns")
def list_columns(model: ModelDependency):
    return sorted(
        s.full_name for s in model.securables.values() if s.securable_type == "column"
    )


@router.get(
    "/column-policies",
    response_model=list[ColumnPolicyOut],
    operation_id="listColumnPolicies",
)
def list_column_policies(model: ModelDependency):
    policy_index = _column_policy_index(model)
    return [
        ColumnPolicyOut(
            column_full_name=column,
            mask_policy_count=len(effects["mask"]),
            row_filter_policy_count=len(effects["filter"]),
        )
        for column, effects in sorted(policy_index.items())
    ]


# --- Explorer questions ----------------------------------------------------------


@router.get(
    "/access", response_model=list[AccessRowOut], operation_id="accessForPrincipal"
)
def access_for_principal(principal: str, model: ModelDependency):
    """Which tables can this principal read (and how)?"""
    rows = []
    for v in readable_tables(model, principal):
        rows.append(
            AccessRowOut(
                securable=v.securable,
                securable_type="table",
                status=v.status,
                masked_columns=[c.column for c in v.columns if c.masked],
                row_filtered=v.row_filtered,
                tags=_tags_of(model, v.securable),
            )
        )
    return rows


@router.get(
    "/columns",
    response_model=list[ColumnAccessRowOut],
    operation_id="columnsForPrincipal",
)
def columns_for_principal(
    principal: str,
    model: ModelDependency,
    filter: Literal["all", "masked", "unmasked"] = "masked",
    table: str | None = None,
    include_inaccessible: bool = False,
):
    """Columns for a principal. Inaccessible columns are opt-in; ``filter``
    remains available for API clients that need mask-specific results."""
    rows: list[ColumnAccessRowOut] = []
    if include_inaccessible:
        can_read_by_table: dict[str, bool] = {}
        explanations = []
        for securable in sorted(
            model.securables.values(),
            key=lambda item: item.full_name,
        ):
            if securable.securable_type != "column":
                continue
            table_full_name = securable.parent_full_name
            if table_full_name is None:
                continue
            if table is not None and table_full_name != table:
                continue
            if table_full_name not in can_read_by_table:
                can_read_by_table[table_full_name] = evaluate(
                    model,
                    principal,
                    table_full_name,
                ).can_read
            explanations.append(
                evaluate_column(
                    model,
                    principal,
                    securable.full_name,
                    can_read_table=can_read_by_table[table_full_name],
                )
            )
    else:
        explanations = masked_columns_for(model, principal)

    for exp in explanations:
        if table is not None and exp.table_full_name != table:
            continue
        if filter == "masked" and not exp.masked:
            continue
        if filter == "unmasked" and exp.masked:
            continue
        row_filter_targeted, row_filtered = row_filter_state_for(
            model,
            principal,
            exp.table_full_name,
            exp.column,
        )
        rows.append(
            ColumnAccessRowOut(
                table=exp.table_full_name,
                column=exp.column,
                column_full_name=exp.column_full_name,
                data_type=exp.data_type,
                can_read_table=exp.can_read_table,
                mask_targeted=exp.policy_name is not None,
                masked=exp.masked,
                row_filtered=row_filtered,
                row_filter_targeted=row_filter_targeted,
                principal=principal,
                policy_name=exp.policy_name,
                tags=_tags_of(model, exp.column_full_name),
            )
        )
    return rows


@router.get(
    "/who-can-see",
    response_model=list[ColumnAccessRowOut],
    operation_id="whoCanSee",
)
def who_can_see(column: str, model: ModelDependency):
    """Who can see this column (masked or unmasked)? ``column`` is the full
    dotted path catalog.schema.table.column."""
    _validate_column(model, column)
    table, _, col_name = column.rpartition(".")
    policy_index = _column_policy_index(model)
    rows: list[ColumnAccessRowOut] = []
    for principal in sorted(model.principals()):
        v = evaluate(model, principal, table)
        if not v.can_read:
            continue
        cv = next((c for c in v.columns if c.column == col_name), None)
        if cv is None:
            continue
        row_filter_targeted, row_filtered = row_filter_state_for(
            model,
            principal,
            table,
            col_name,
        )
        rows.append(
            ColumnAccessRowOut(
                table=table,
                column=col_name,
                column_full_name=column,
                data_type=cv.data_type,
                can_read_table=v.can_read,
                mask_targeted=bool(policy_index.get(column, {}).get("mask")),
                masked=cv.masked,
                row_filtered=row_filtered,
                row_filter_targeted=row_filter_targeted,
                principal=principal,
                tags=_tags_of(model, column),
            )
        )
    return rows


# --- Why + graph ------------------------------------------------------------------


@router.get("/explain", response_model=VerdictOut, operation_id="explain")
def explain(principal: str, table: str, model: ModelDependency):
    """Full verdict + why-chains for one (principal, table)."""
    return _verdict_out(model, principal, table)


@router.get(
    "/explain-column", response_model=ColumnExplanationOut, operation_id="explainColumn"
)
def explain_column(principal: str, column: str, model: ModelDependency):
    """Mask verdict + deciding policy for one (principal, column). ``column``
    is the full dotted path catalog.schema.table.column."""
    _validate_column(model, column)
    exp = evaluate_column(model, principal, column)
    row_filter_targeted, row_filtered, row_filter_excepted_by = (
        row_filter_state_details_for(
            model,
            principal,
            exp.table_full_name,
            exp.column,
        )
    )
    return ColumnExplanationOut(
        principal=exp.principal,
        column_full_name=exp.column_full_name,
        table_full_name=exp.table_full_name,
        column=exp.column,
        data_type=exp.data_type,
        can_read_table=exp.can_read_table,
        masked=exp.masked,
        row_filtered=row_filtered,
        row_filter_targeted=row_filter_targeted,
        row_filter_excepted_by=row_filter_excepted_by,
        policy_name=exp.policy_name,
        function=exp.function,
        covered_by=exp.covered_by,
        excepted_by=exp.excepted_by,
        tag_atoms=dict(exp.tag_atoms),
        policy_attached_to=exp.policy_attached_to,
        policy_attached_level=exp.policy_attached_level,
        policy_source=exp.policy_source,
        arguments=[PolicyArgumentOut(**vars(argument)) for argument in exp.arguments],
        sentence=exp.sentence,
    )


def _chain_node_out(n, build) -> ChainGraphNodeOut:
    return ChainGraphNodeOut(
        id=n.id,
        kind=n.kind,
        label=n.label,
        layer=n.layer,
        sublabel=n.sublabel,
        source=n.source,
        github_url=(
            build.github_url(n.source_file, n.source_line) if n.source_file else None
        ),
    )


def _chain_edge_out(edge, build) -> ChainGraphEdgeOut:
    code_sources = []
    if edge.source_file and edge.source_securable and edge.source_securable_type:
        code_sources.append(
            GraphSourceOut(
                securable=edge.source_securable,
                securable_type=edge.source_securable_type,
                source=(
                    f"{edge.source_file}:{edge.source_line}"
                    if edge.source_line
                    else edge.source_file
                ),
                github_url=build.github_url(edge.source_file, edge.source_line),
            )
        )
    return ChainGraphEdgeOut(
        source=edge.source,
        target=edge.target,
        label=edge.label,
        kind=edge.kind,
        code_sources=code_sources,
    )


@router.get(
    "/explain-column-graph",
    response_model=ChainGraphOut,
    operation_id="explainColumnGraph",
)
def explain_column_graph(
    principal: str, column: str, model: ModelDependency, build: BuildInfoDependency
):
    """Column mask flow as a graph: principal → group → mask policy → tag →
    column. The 'tagged on' edges are a distinct kind so the frontend can hide
    them for the simplified view."""
    _validate_column(model, column)
    g = build_column_chain_graph(model, principal, column)
    return ChainGraphOut(
        principal=g.principal,
        securable=g.securable,
        nodes=[_chain_node_out(n, build) for n in g.nodes],
        edges=[_chain_edge_out(e, build) for e in g.edges],
    )


@router.get("/explain-graph", response_model=ChainGraphOut, operation_id="explainGraph")
def explain_graph(
    principal: str,
    table: str,
    model: ModelDependency,
    build: BuildInfoDependency,
    include_column_masks: bool = True,
    include_row_filters: bool = True,
    include_grants: bool = True,
    focus_column: str | None = None,
):
    """The why chain as a layered graph: user → subgroup → group → policy →
    tag → securable (with containment/inheritance edges). Set
    include_column_masks=false for the table view (per-column mask detail lives
    on the column Why page)."""
    g = build_chain_graph(
        model,
        principal,
        table,
        include_column_masks=include_column_masks,
        include_row_filters=include_row_filters,
        include_grants=include_grants,
        focus_column=focus_column,
    )
    return ChainGraphOut(
        principal=g.principal,
        securable=g.securable,
        nodes=[_chain_node_out(n, build) for n in g.nodes],
        edges=[_chain_edge_out(e, build) for e in g.edges],
    )


@router.get("/graph", response_model=GraphOut, operation_id="accessGraph")
def access_graph(principal: str, model: ModelDependency, build: BuildInfoDependency):
    """Progressive User → Groups → Policies → Tags → Tables trace graph.

    Grant paths are those reachable via the principal, directly or through groups.
    Catalog and schema grant effects are projected onto the readable descendant tables
    they enable, so the final hop is always a table. Drift (privileges a grant policy
    expects but Unity Catalog does not hold) grants no access, so its securables may
    be unreadable; it is drawn as-is. Row filtering changes a table's rows, so the
    effective state is carried on table nodes rather than projected onto the
    predicate's input columns.
    """
    nodes: dict[str, GraphNodeOut] = {}
    edges: list[GraphEdgeOut] = []
    seen_membership: set[tuple[str, str]] = set()
    seen_policy_edges: set[tuple[str, str]] = set()
    seen_match_edges: set[tuple[str, str]] = set()
    grant_labels: dict[tuple[str, str, str, str], set[str]] = {}
    grant_code_sources: dict[tuple[str, str, str, str], dict[str, GraphSourceOut]] = {}

    def add_node(
        node_id: str,
        kind: str,
        label: str | None = None,
        provenance=None,
        link_source: bool = True,
    ):
        source = None
        github_url = None
        if provenance is not None:
            source = (
                f"{provenance.file}:{provenance.line}"
                if provenance.line
                else provenance.file
            )
            if link_source:
                github_url = build.github_url(provenance.file, provenance.line)
        existing = nodes.get(node_id)
        replace = existing is None or (
            existing.github_url is None and github_url is not None
        )
        if replace:
            nodes[node_id] = GraphNodeOut(
                id=node_id,
                kind=kind,
                label=label or (existing.label if existing else node_id),
                source=source or (existing.source if existing else None),
                github_url=github_url or (existing.github_url if existing else None),
            )

    def add_membership_edge(source: str, target: str, label: str = "member"):
        if (source, target) not in seen_membership:
            seen_membership.add((source, target))
            edges.append(
                GraphEdgeOut(
                    source=source,
                    target=target,
                    label=label,
                    kind="membership",
                )
            )

    all_groups = model.groups_of(principal)
    membership_rows = [
        edge
        for edge in model.membership_closure
        if edge.member == principal and edge.group in all_groups
    ]
    group_provenance = {
        edge.group: edge.provenance
        for edge in sorted(membership_rows, key=lambda edge: edge.group)
    }
    direct_memberships = sorted(
        (edge for edge in membership_rows if edge.direct),
        key=lambda edge: edge.group,
    )
    add_node(
        principal,
        "user",
        provenance=direct_memberships[0].provenance if direct_memberships else None,
        link_source=False,
    )
    for g in sorted(all_groups):
        add_node(g, "group", provenance=group_provenance.get(g))
    for e in model.membership_closure:
        if e.member == principal and e.direct:
            add_membership_edge(principal, e.group)
    # group→group nesting edges within the principal's closure
    for parent, members in model.groups.items():
        if parent not in all_groups:
            continue
        for child in members:
            if child in all_groups:
                add_membership_edge(child, parent)

    readable_verdicts = {
        verdict.securable: verdict
        for verdict in readable_tables(model, principal)
        if verdict.can_read
    }
    readable = set(readable_verdicts)

    # grant paths reachable via the principal (see docstring)
    for gm in model.grant_matches:
        if not model.principal_matches(principal, gm.principal):
            continue
        anchor = gm.matched_securable_full_name or gm.securable_full_name
        anchor_sec = model.securables.get(anchor)
        if anchor_sec is None:
            continue
        targets = (
            {anchor}
            if anchor_sec.securable_type == "table"
            else {table for table in readable if table.startswith(f"{anchor}.")}
        )
        targets &= readable
        if not targets:
            continue

        source_kind = "user" if gm.principal == principal else "group"
        add_node(
            gm.principal,
            source_kind,
            provenance=group_provenance.get(gm.principal),
            link_source=source_kind != "user",
        )
        if gm.principal == ALL_USERS_GROUP:
            add_membership_edge(principal, gm.principal, "member (implicit)")

        policy = model.grant_policies[gm.policy_id]
        manual = policy.origin == "direct"
        add_node(
            policy.policy_id,
            "manual" if manual else "policy",
            policy.parent_full_name if manual else policy.name,
            policy.provenance,
        )
        policy_key = (gm.principal, policy.policy_id)
        if policy_key not in seen_policy_edges:
            seen_policy_edges.add(policy_key)
            edges.append(
                GraphEdgeOut(
                    source=gm.principal,
                    target=policy.policy_id,
                    label="in 'to'",
                    kind="to",
                    policy_id=policy.policy_id,
                )
            )

        for table in targets:
            add_node(
                table,
                "table",
                provenance=(
                    model.securables[table].provenance
                    if table in model.securables
                    else None
                ),
            )
            if gm.matched_tags:
                for tag_name, tag_value in gm.matched_tags:
                    tag_id = f"tag:{policy.policy_id}:{tag_name}={tag_value}"
                    tag_assignment = next(
                        (
                            assignment
                            for assignment in model.tag_assignments
                            if assignment.securable_full_name == anchor
                            and assignment.tag_name == tag_name
                            and assignment.tag_value == tag_value
                        ),
                        None,
                    )
                    add_node(
                        tag_id,
                        "tag",
                        f"{tag_name}={tag_value}",
                        tag_assignment.provenance if tag_assignment else None,
                        link_source=False,
                    )
                    match_key = (policy.policy_id, tag_id)
                    if match_key not in seen_match_edges:
                        seen_match_edges.add(match_key)
                        edges.append(
                            GraphEdgeOut(
                                source=policy.policy_id,
                                target=tag_id,
                                label="matches",
                                kind="matches",
                                policy_id=policy.policy_id,
                            )
                        )
                    edge_key = (tag_id, table, "tagged", policy.policy_id)
                    labels = grant_labels.setdefault(edge_key, set())
                    tagged_provenance = (
                        tag_assignment.provenance
                        if tag_assignment
                        else anchor_sec.provenance
                    )
                    tagged_source = None
                    tagged_url = None
                    if tagged_provenance is not None:
                        tagged_source = (
                            f"{tagged_provenance.file}:{tagged_provenance.line}"
                            if tagged_provenance.line
                            else tagged_provenance.file
                        )
                        tagged_url = build.github_url(
                            tagged_provenance.file,
                            tagged_provenance.line,
                        )
                    grant_code_sources.setdefault(edge_key, {})[anchor] = (
                        GraphSourceOut(
                            securable=anchor,
                            securable_type=anchor_sec.securable_type,
                            source=tagged_source,
                            github_url=tagged_url,
                            inherited=anchor != table,
                        )
                    )
                    labels.add(gm.privilege)
            else:
                grant_kind = "manual_grant" if manual else "grant"
                edge_key = (policy.policy_id, table, grant_kind, policy.policy_id)
                labels = grant_labels.setdefault(edge_key, set())
                labels.add(gm.privilege)

    # drift: expected privileges UC does not hold (see docstring)
    seen_drift_edges: set[tuple[str, str, str]] = set()
    for drift in model.drift:
        if not model.principal_matches(principal, drift.principal):
            continue
        policy = model.grant_policies[drift.policy_id]
        grantee_kind = "user" if drift.principal == principal else "group"
        add_node(
            drift.principal,
            grantee_kind,
            provenance=group_provenance.get(drift.principal),
            link_source=grantee_kind != "user",
        )
        if drift.principal == ALL_USERS_GROUP:
            add_membership_edge(principal, drift.principal, "member (implicit)")
        add_node(policy.policy_id, "policy", policy.name, policy.provenance)
        if (drift.principal, policy.policy_id) not in seen_policy_edges:
            seen_policy_edges.add((drift.principal, policy.policy_id))
            edges.append(
                GraphEdgeOut(
                    source=drift.principal,
                    target=policy.policy_id,
                    label="in 'to'",
                    kind="to",
                    policy_id=policy.policy_id,
                )
            )
        securable = model.securables.get(drift.securable_full_name)
        add_node(
            drift.securable_full_name,
            drift.securable_type,
            provenance=securable.provenance if securable else None,
        )
        drift_key = (policy.policy_id, drift.securable_full_name, drift.privilege)
        if drift_key in seen_drift_edges:
            continue
        seen_drift_edges.add(drift_key)
        edges.append(
            GraphEdgeOut(
                source=policy.policy_id,
                target=drift.securable_full_name,
                label=f"{_uc_privilege(drift.privilege)} expected, not held",
                kind="drift",
                policy_id=policy.policy_id,
            )
        )

    edges.extend(
        GraphEdgeOut(
            source=source,
            target=table,
            label=_grant_edge_label(labels),
            kind=kind,
            policy_id=policy_id,
            code_sources=sorted(
                grant_code_sources.get((source, table, kind, policy_id), {}).values(),
                key=lambda tagged: (tagged.securable.count("."), tagged.securable),
                reverse=True,
            ),
        )
        for (source, table, kind, policy_id), labels in grant_labels.items()
    )
    # effective row-filter state on table nodes (see docstring)
    for table, verdict in readable_verdicts.items():
        node = nodes.get(table)
        if node is not None:
            row_filter_targeted, _row_filtered = row_filter_state_for(
                model, principal, table
            )
            nodes[table] = node.model_copy(
                update={
                    "row_filter_targeted": row_filter_targeted,
                    "row_filtered": verdict.row_filtered,
                }
            )

    return GraphOut(principal=principal, nodes=list(nodes.values()), edges=edges)


def _access_edges(graph: GraphOut) -> list[GraphEdgeOut]:
    """The edges of ``graph`` that are real access paths.

    Drift edges mark a grant that is expected but not held, so they never carry
    access and are dropped before walking paths to a securable.
    """
    return [edge for edge in graph.edges if edge.kind != "drift"]


@router.get(
    "/inverse-graph",
    response_model=InverseGraphOut,
    operation_id="inverseAccessGraph",
)
def inverse_access_graph(
    securable: str,
    model: ModelDependency,
    build: BuildInfoDependency,
):
    """All readable principal paths to one table or column."""
    target = model.securables.get(securable)
    if target is None or target.securable_type not in {"table", "column"}:
        raise HTTPException(
            status_code=404,
            detail=f"table or column not found: {securable}",
        )
    table = (
        securable if target.securable_type == "table" else securable.rsplit(".", 1)[0]
    )
    selected_column = (
        None if target.securable_type == "table" else securable.rsplit(".", 1)[1]
    )
    principal_kinds = {
        principal.name: principal.kind for principal in list_principals(model)
    }
    nodes: dict[str, GraphNodeOut] = {}
    edges: dict[tuple[str, str, str, str, str | None], GraphEdgeOut] = {}
    effects: list[PrincipalEffectOut] = []
    policy_index = _column_policy_index(model)

    for principal, principal_kind in sorted(principal_kinds.items()):
        verdict = evaluate(model, principal, table)
        if not verdict.can_read:
            continue
        if selected_column and not any(
            column.column == selected_column for column in verdict.columns
        ):
            continue

        masked_columns = [
            f"{table}.{column.column}"
            for column in verdict.columns
            if column.masked
            and (selected_column is None or column.column == selected_column)
        ]
        mask_policy_columns: list[str] = []
        row_filter_policy_columns: list[str] = []
        row_filter_columns = []
        for column in verdict.columns:
            column_full_name = f"{table}.{column.column}"
            policy_effects = policy_index.get(column_full_name, {})
            if policy_effects.get("mask") and (
                selected_column is None or column.column == selected_column
            ):
                mask_policy_columns.append(column_full_name)
            if policy_effects.get("filter"):
                row_filter_policy_columns.append(column_full_name)
            targeted, filtered = row_filter_state_for(
                model,
                principal,
                table,
                column.column,
            )
            if targeted and filtered:
                row_filter_columns.append(f"{table}.{column.column}")

        row_filter_targeted, _row_filtered = row_filter_state_for(
            model, principal, table
        )

        effects.append(
            PrincipalEffectOut(
                principal=principal,
                principal_kind=principal_kind,
                mask_targeted=bool(mask_policy_columns),
                masked=bool(masked_columns),
                row_filter_targeted=row_filter_targeted,
                row_filtered=verdict.row_filtered,
                masked_columns=masked_columns,
                row_filter_columns=row_filter_columns,
                mask_policy_columns=mask_policy_columns,
                row_filter_policy_columns=row_filter_policy_columns,
            )
        )

        principal_graph = access_graph(principal, model, build)
        access_edges = _access_edges(principal_graph)
        incoming: dict[str, list[GraphEdgeOut]] = {}
        for edge in access_edges:
            incoming.setdefault(edge.target, []).append(edge)
        path_nodes = {table}
        queue = [table]
        while queue:
            node_id = queue.pop()
            for edge in incoming.get(node_id, []):
                if edge.source in path_nodes:
                    continue
                path_nodes.add(edge.source)
                queue.append(edge.source)

        for node in principal_graph.nodes:
            if node.id not in path_nodes:
                continue
            if node.id == principal:
                node = node.model_copy(
                    update={
                        "kind": "group" if principal_kind == "group" else "user",
                        "effect_principal": True,
                        "mask_targeted": principal_kind != "group"
                        and bool(mask_policy_columns),
                        "masked": principal_kind != "group" and bool(masked_columns),
                        "row_filter_targeted": principal_kind != "group"
                        and row_filter_targeted,
                        "row_filtered": principal_kind != "group"
                        and verdict.row_filtered,
                    }
                )
            existing = nodes.get(node.id)
            if existing is None or node.effect_principal:
                nodes[node.id] = node
        for edge in access_edges:
            if edge.source not in path_nodes or edge.target not in path_nodes:
                continue
            key = (edge.source, edge.target, edge.kind, edge.label, edge.policy_id)
            edges.setdefault(key, edge)

    if selected_column and table in nodes:
        nodes[securable] = GraphNodeOut(
            id=securable,
            kind="column",
            label=selected_column,
        )
        edges[(table, securable, "contains", "column", None)] = GraphEdgeOut(
            source=table,
            target=securable,
            kind="contains",
            label="column",
        )

    return InverseGraphOut(
        principal="all",
        target=securable,
        target_type=target.securable_type,
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        principal_effects=effects,
    )
