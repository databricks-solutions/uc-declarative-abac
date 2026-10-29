from pathlib import Path

from abac_viewer.backend.engine import build_chain_graph, grouped_chains
from tests.unit.abac_viewer.dump_fixtures import load_dump_model

FIXTURE = Path(__file__).parent / "fixtures" / "parallel_grants"
PRINCIPAL = "sp_engineer"
TABLE = "acme.finance.budgets"


def test_table_why_graph_keeps_parallel_grant_chains():
    graph = build_chain_graph(
        load_dump_model(FIXTURE),
        PRINCIPAL,
        TABLE,
        include_column_masks=False,
        include_row_filters=False,
    )

    node_ids = {node.id for node in graph.nodes}
    edges = {(edge.source, edge.target, edge.kind) for edge in graph.edges}

    assert {"acme#grant_finance_read", "acme#grant_platform_zones"} <= node_ids
    assert (PRINCIPAL, "finance_readers", "member") in edges
    assert (PRINCIPAL, "engineers", "member") in edges
    assert ("engineers", "data_platform", "member") in edges
    assert ("finance_readers", "acme#grant_finance_read", "to") in edges
    assert ("data_platform", "acme#grant_platform_zones", "to") in edges
    assert ("tag:team=finance", "acme.finance", "tagged") in edges
    assert ("tag:zone=silver", "acme.finance", "tagged") in edges
    assert ("acme.finance", TABLE, "inherit") in edges


def test_table_why_detail_keeps_parallel_grant_chains():
    groups = grouped_chains(load_dump_model(FIXTURE), PRINCIPAL, TABLE)
    grant_groups = {
        group.policy.label: group
        for group in groups
        if group.policy.label.startswith("grant policy")
    }

    assert set(grant_groups) == {
        "grant policy 'grant_finance_read'",
        "grant policy 'grant_platform_zones'",
    }
    assert {group.membership.label for group in grant_groups.values()} == {
        "sp_engineer ∈ finance_readers",
        "sp_engineer ∈ data_platform",
    }
    for group in grant_groups.values():
        assert {effect.label for effect in group.effects} == {
            "USE_CATALOG on acme",
            "USE_SCHEMA on acme.finance",
            "SELECT on acme.finance",
        }
