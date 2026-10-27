"""Divergence from the config (manual grants and drift) in the HTTP API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abac_viewer.backend.engine.dump import (
    InMemoryDumpReader,
    load_factored_model_from_dump,
)
from abac_viewer.backend.engine.model import FactoredModel
from abac_viewer.backend.engine.runtime import BuildInfo
from abac_viewer.backend.router import access_graph, inverse_access_graph, meta
from tests.unit.abac_viewer.dump_fixtures import dump_rows_from_config

NESTED = Path(__file__).parent / "fixtures" / "nested"
BUILD = BuildInfo(sha="main", repo_slug="", config_path_prefix="")


def _row(rows: dict[str, list[dict[str, Any]]], table: str, **match: Any) -> dict:
    found = [r for r in rows[table] if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, f"expected one {table} row matching {match}"
    return found[0]


def _privilege_row(grantee, privilege_type, securable_type, schema, name) -> dict:
    return {
        "config_file_path": None,
        "grantee": grantee,
        "grantee_id": None,
        "grantee_type": "USER",
        "catalog_name": "acme",
        "schema_name": schema,
        "securable_name": name,
        "securable_type": securable_type,
        "privilege_type": privilege_type,
    }


def _model(rows: dict[str, list[dict[str, Any]]]) -> FactoredModel:
    return load_factored_model_from_dump(InMemoryDumpReader(rows))


def _with_manual_grants() -> FactoredModel:
    rows = dump_rows_from_config(NESTED)
    rows["securable_privileges"] = [
        *rows["securable_privileges"],
        _privilege_row("manual_user", "USE CATALOG", "CATALOG", None, "acme"),
        _privilege_row("manual_user", "USE SCHEMA", "SCHEMA", "sales", "sales"),
        _privilege_row("manual_user", "SELECT", "TABLE", "sales", "orders"),
    ]
    return _model(rows)


def _analyst_select_revoked_rows() -> dict[str, list[dict[str, Any]]]:
    rows = dump_rows_from_config(NESTED)
    rows["securable_privileges"] = [
        row
        for row in rows["securable_privileges"]
        if not (
            row["grantee"] == "analysts"
            and row["securable_name"] == "orders"
            and row["privilege_type"] == "SELECT"
        )
    ]
    return rows


def _with_analyst_select_revoked() -> FactoredModel:
    return _model(_analyst_select_revoked_rows())


# ---------------------------------------------------------------------------
# manual grants
# ---------------------------------------------------------------------------


def test_router_access_graph_shows_manual_grants_apart_from_policies():
    graph = access_graph("manual_user", _with_manual_grants(), BUILD)

    manual = [n for n in graph.nodes if n.kind == "manual"]
    assert manual
    # Each manual grant is labelled by the securable it was granted on.
    assert {n.label for n in manual} == {"acme", "acme.sales", "acme.sales.orders"}
    assert not any(
        n.kind == "policy" and n.id.startswith("direct:") for n in graph.nodes
    )
    manual_ids = {n.id for n in manual}
    grant_edges = [e for e in graph.edges if e.source in manual_ids]
    assert any(e.target == "acme.sales.orders" for e in grant_edges)
    assert all(e.kind == "manual_grant" for e in grant_edges)


def test_router_access_graph_labels_prerequisite_grants_by_privilege():
    graph = access_graph("manual_user", _with_manual_grants(), BUILD)

    labels = {n.id: n.label for n in graph.nodes}
    into_orders = {
        labels[e.source]: e.label
        for e in graph.edges
        if e.kind == "manual_grant" and e.target == "acme.sales.orders"
    }
    assert into_orders == {
        "acme": "USE CATALOG",
        "acme.sales": "USE SCHEMA",
        "acme.sales.orders": "SELECT",
    }


def test_router_access_graph_never_labels_an_edge_prerequisite():
    model = _with_manual_grants()

    for principal in ("manual_user", "sp_alice", "analysts"):
        graph = access_graph(principal, model, BUILD)
        assert not any(e.label == "prerequisite" for e in graph.edges), principal


def _with_traversal_grant() -> FactoredModel:
    """The nested fixture plus a tagged catalog grant that supplies only USE on gold
    tables, so sp_alice's SELECT on orders still comes from ``grant_gold_read``."""
    rows = dump_rows_from_config(NESTED)
    gold = _row(rows, "pseudo_policies", policy_name="grant_gold_read")
    traverse = {**gold, "policy_name": "grant_gold_traverse", "privileges": ("USE",)}
    rows["pseudo_policies"] = [*rows["pseudo_policies"], traverse]
    return _model(rows)


def test_router_access_graph_labels_tagged_grant_by_its_own_privileges():
    graph = access_graph("sp_alice", _with_traversal_grant(), BUILD)

    into_orders = [
        e for e in graph.edges if e.kind == "tagged" and e.target == "acme.sales.orders"
    ]
    traverse = [e for e in into_orders if e.policy_id == "acme#grant_gold_traverse"]
    select = [e for e in into_orders if e.policy_id == "acme#grant_gold_read"]
    assert select and {e.label for e in select} == {"SELECT"}
    assert traverse
    for edge in traverse:
        assert edge.label != "SELECT", edge
        assert edge.label
        assert set(edge.label.split(", ")) <= {"USE CATALOG", "USE SCHEMA"}, edge


def test_router_access_graph_keeps_policy_grants_as_policies():
    graph = access_graph("sp_alice", _with_manual_grants(), BUILD)

    assert any(n.kind == "policy" for n in graph.nodes)
    assert not any(n.kind == "manual" for n in graph.nodes)
    assert not any(e.kind in {"manual_grant", "drift"} for e in graph.edges)


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------


def test_router_access_graph_shows_drift_from_policy_to_securable():
    model = _with_analyst_select_revoked()

    for principal in ("analysts", "sp_alice"):
        graph = access_graph(principal, model, BUILD)
        nodes = {n.id: n for n in graph.nodes}
        drift = [e for e in graph.edges if e.kind == "drift"]

        assert drift, principal
        edge = next(e for e in drift if e.target == "acme.sales.orders")
        assert edge.source == "acme#grant_gold_read"
        assert "SELECT" in edge.label
        assert nodes["acme.sales.orders"].kind == "table"
        assert nodes["acme#grant_gold_read"].kind == "policy"


def test_router_access_graph_has_no_drift_for_unaffected_principals():
    graph = access_graph("sp_erin", _with_analyst_select_revoked(), BUILD)

    assert not any(e.kind == "drift" for e in graph.edges)


def test_router_meta_lists_drift_with_the_path_to_open():
    out = meta(_with_analyst_select_revoked(), BUILD)

    item = next(d for d in out.drift if d.securable == "acme.sales.orders")
    assert item.principal == "analysts"
    assert item.policy_id == "acme#grant_gold_read"
    assert item.policy_name == "grant_gold_read"
    assert item.privilege == "SELECT"
    assert item.securable_type == "table"


def test_router_meta_lists_no_drift_when_nothing_diverged():
    out = meta(_model(dump_rows_from_config(NESTED)), BUILD)

    assert out.drift == []


def test_router_inverse_graph_does_not_walk_drift_edges():
    rows = _analyst_select_revoked_rows()
    rows["securable_privileges"] = [
        *rows["securable_privileges"],
        _privilege_row("sp_alice", "USE CATALOG", "CATALOG", None, "acme"),
        _privilege_row("sp_alice", "USE SCHEMA", "SCHEMA", "sales", "sales"),
        _privilege_row("sp_alice", "SELECT", "TABLE", "sales", "orders"),
    ]

    graph = inverse_access_graph("acme.sales.orders", _model(rows), BUILD)

    assert not any(e.kind == "drift" for e in graph.edges)
    assert not any("expected, not held" in (e.label or "") for e in graph.edges)
    assert any(n.kind == "manual" for n in graph.nodes)


def _with_shared_schema_grant_revoked() -> FactoredModel:
    """``grant_platform_schema`` granted to both ``data_platform`` and its member
    ``engineers``, with its schema privileges revoked from both. sp_erin is in both
    groups, so each expected privilege drifts once per group."""
    rows = dump_rows_from_config(NESTED)
    dp = _row(rows, "principals", display_name="data_platform")
    eng = _row(rows, "principals", display_name="engineers")
    schema_grant = _row(rows, "pseudo_policies", policy_name="grant_platform_schema")
    rows["pseudo_policies"] = [
        *[r for r in rows["pseudo_policies"] if r is not schema_grant],
        {
            **schema_grant,
            "to_principals": ("data_platform", "engineers"),
            "to_principal_ids": (dp["principal_id"], eng["principal_id"]),
        },
    ]
    rows["securable_privileges"] = [
        row
        for row in rows["securable_privileges"]
        if not (
            row["grantee"] in {"data_platform", "engineers"}
            and row["securable_type"] == "SCHEMA"
            and row["securable_name"] == "sales"
        )
    ]
    return _model(rows)


def test_router_access_graph_emits_one_drift_edge_per_policy_target_and_label():
    graph = access_graph("sp_erin", _with_shared_schema_grant_revoked(), BUILD)

    drift = [e for e in graph.edges if e.kind == "drift"]
    assert drift
    keys = [(e.source, e.target, e.label) for e in drift]
    assert len(keys) == len(set(keys)), keys


# ---------------------------------------------------------------------------
# warnings and drift
# ---------------------------------------------------------------------------


def test_router_meta_reports_drift_only_as_drift_not_as_warning():
    out = meta(_with_analyst_select_revoked(), BUILD)

    assert out.drift
    assert not any(
        "acme#grant_gold_read" in w and "acme.sales.orders" in w for w in out.warnings
    )


def test_router_meta_warnings_exclude_drift_and_keep_other_warnings():
    rows = _analyst_select_revoked_rows()
    tagged = _row(rows, "securable_tags", securable_name="orders", tag_name="zone")
    rows["securable_tags"] = [
        *rows["securable_tags"],
        {**tagged, "tag_value": "platinum"},
    ]
    model = _model(rows)

    out = meta(model, BUILD)

    assert out.warnings == model.warnings
    assert not any("drift" in w for w in model.warnings)
    assert any("platinum" in w for w in out.warnings)
