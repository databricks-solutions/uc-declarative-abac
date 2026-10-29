"""Regression tests for column-scoped explanations and chain graphs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from abac_viewer.backend.engine.chain_graph import (
    build_chain_graph,
    build_column_chain_graph,
)
from abac_viewer.backend.engine.model import CompiledFgacPolicy, FgacMatch
from abac_viewer.backend.engine.verdict import (
    evaluate,
    evaluate_column,
    grouped_chains,
    row_filter_state_details_for,
    row_filter_state_for,
)
from tests.unit.abac_viewer.dump_fixtures import load_dump_model

FIXTURE = Path(__file__).parent / "fixtures" / "nested"
POLICY_ARGUMENTS_FIXTURE = Path(__file__).parent / "fixtures" / "policy_arguments"
FILTER_ALIASES_FIXTURE = Path(__file__).parent / "fixtures" / "filter_aliases"
DEMO_FIXTURE = Path(__file__).parents[3] / "examples" / "abac_viewer_demo" / "configs"
TABLE = "acme.sales.orders"
COLUMN = f"{TABLE}.customer_email"


@pytest.fixture(scope="module")
def model():
    return load_dump_model(FIXTURE)


def test_column_explanation_matches_masked_table_verdict(model):
    table_verdict = evaluate(model, "sp_alice", TABLE)
    column_verdict = evaluate_column(model, "sp_alice", COLUMN)

    table_column = next(
        column for column in table_verdict.columns if column.column == "customer_email"
    )
    assert table_column.masked
    assert column_verdict.masked
    assert column_verdict.can_read_table
    assert column_verdict.policy_name == "mask_pii"
    assert column_verdict.covered_by == "account users"
    assert column_verdict.tag_atoms == (("pii", "email"),)
    assert "MASKED" in column_verdict.sentence


def test_column_explanation_identifies_exception(model):
    explanation = evaluate_column(model, "sp_frank", COLUMN)

    assert not explanation.can_read_table
    assert not explanation.masked
    assert explanation.policy_name == "mask_pii"
    assert explanation.excepted_by == "auditors"
    assert "exempt" in explanation.sentence


def test_column_graph_identifies_exception_path(model):
    graph = build_column_chain_graph(model, "sp_frank", COLUMN)

    assert any(node.id == "auditors" for node in graph.nodes)
    assert any(
        edge.target == "acme#mask_pii" and edge.label == "in 'except' (exempt)"
        for edge in graph.edges
    )
    assert any(edge.label == "EXEMPT (mask)" for edge in graph.edges)


def test_table_graph_can_hide_masks_without_hiding_row_filters(model):
    graph = build_chain_graph(
        model,
        "sp_alice",
        TABLE,
        include_column_masks=False,
    )

    node_ids = {node.id for node in graph.nodes}
    assert "acme#mask_pii" not in node_ids
    assert "acme.sales#filter_gold_rows" in node_ids
    assert not any(node.kind == "column" for node in graph.nodes)
    assert any(edge.label == "FILTERS ROWS" for edge in graph.edges)


def test_table_graph_can_separate_grants_from_row_filters(model):
    grant_graph = build_chain_graph(
        model,
        "sp_alice",
        TABLE,
        include_column_masks=False,
        include_row_filters=False,
    )
    filter_graph = build_chain_graph(
        model,
        "sp_alice",
        TABLE,
        include_column_masks=False,
        include_grants=False,
    )

    assert any(node.id == "acme#grant_gold_read" for node in grant_graph.nodes)
    assert not any(
        node.id == "acme.sales#filter_gold_rows" for node in grant_graph.nodes
    )
    assert any(node.id == "acme.sales#filter_gold_rows" for node in filter_graph.nodes)
    assert not any(node.id == "acme#grant_gold_read" for node in filter_graph.nodes)
    assert any(edge.label == "FILTERS ROWS" for edge in filter_graph.edges)


def test_row_filter_state_is_scoped_to_filter_input_columns():
    alias_model = load_dump_model(FILTER_ALIASES_FIXTURE)
    table = "edge.sales.complete"

    assert row_filter_state_for(alias_model, "someone", table, "region") == (
        True,
        True,
    )
    assert row_filter_state_for(alias_model, "someone", table, "classification") == (
        True,
        True,
    )
    assert row_filter_state_for(alias_model, "someone", table, "email") == (
        False,
        False,
    )


def test_row_filter_state_reports_matching_exception():
    demo_model = load_dump_model(DEMO_FIXTURE)

    assert row_filter_state_details_for(
        demo_model,
        "abac_demo_sp_eng_1",
        "abac_viz_demo.sales.customers",
        "region",
    ) == (True, False, "abac_demo_data_platform")


def test_row_filter_graph_excludes_policies_for_other_columns():
    alias_model = load_dump_model(FILTER_ALIASES_FIXTURE)
    table = "edge.sales.complete"
    region_graph = build_chain_graph(
        alias_model,
        "someone",
        table,
        include_column_masks=False,
        include_grants=False,
        focus_column="region",
    )
    email_graph = build_chain_graph(
        alias_model,
        "someone",
        table,
        include_column_masks=False,
        include_grants=False,
        focus_column="email",
    )

    assert any(node.id == "edge#filter_with_aliases" for node in region_graph.nodes)
    assert not any(node.id == table for node in region_graph.nodes)
    assert not any(edge.target == table for edge in region_graph.edges)
    assert not any(node.id == "edge#filter_with_aliases" for node in email_graph.nodes)


def test_table_scoped_row_filter_graph_shows_every_table_and_column_tag():
    demo_model = load_dump_model(DEMO_FIXTURE)
    table = "abac_viz_demo.sales.trips"
    graph = build_chain_graph(
        demo_model,
        "abac_demo_sp_ana_emea_1",
        table,
        include_column_masks=False,
        include_grants=False,
    )
    node_ids = {node.id for node in graph.nodes}

    assert {
        table,
        f"{table}.from_region",
        f"{table}.to_region",
        "tag:abac_demo_sensitivity=high",
        "tag:abac_demo_trips=trip",
        "tag:abac_demo_from_region=region",
        "tag:abac_demo_to_region=region",
    } <= node_ids
    assert any(
        edge.target == table and edge.label == "FILTERS ROWS" for edge in graph.edges
    )
    tagged_edges = [edge for edge in graph.edges if edge.kind == "tagged"]
    assert {edge.target for edge in tagged_edges} == {
        table,
        f"{table}.from_region",
        f"{table}.to_region",
    }
    assert all(edge.source_file for edge in tagged_edges)


def test_grouped_chain_detail_deduplicates_grant_prerequisites(model):
    groups = grouped_chains(model, "sp_alice", TABLE)

    assert len(groups) == 2
    grant_group = next(
        group for group in groups if "grant policy" in group.policy.label
    )
    filter_group = next(
        group for group in groups if "filter policy" in group.policy.label
    )
    assert grant_group.policy.label == "grant policy 'grant_gold_read'"
    assert {effect.label for effect in grant_group.effects} == {
        "USE_CATALOG on acme",
        "USE_SCHEMA on acme.sales",
        "SELECT on acme.sales.orders",
    }
    assert {effect.label for effect in filter_group.effects} == {
        "ROWS FILTERED by acme.sales.fn_region_filter"
    }


def _model_with_noncovering_mask_first(model):
    modified = deepcopy(model)
    policy_id = "acme#mask_pii_noncovering"
    modified.fgac_policies[policy_id] = CompiledFgacPolicy(
        policy_id=policy_id,
        name="mask_pii_noncovering",
        policy_type="mask",
        parent_full_name="acme",
        has_tags=(("zone", "*"),),
        has_any_of_tags=(),
        function="acme.fn_mask_noncovering",
        to=("unrelated_group",),
        exceptions=(),
        column_arguments=(),
        match_columns=(("pii_column", (("pii", "*"),), ()),),
        match_column_has_tags=(("pii", "*"),),
        match_column_has_any_of_tags=(),
        comment=None,
    )
    modified.fgac_matches.insert(
        0,
        FgacMatch(
            policy_id=policy_id,
            table_full_name=TABLE,
            matched_table_tags=(("zone", "gold"),),
            matched_columns=(("customer_email", (("pii", "email"),)),),
        ),
    )
    return modified, policy_id


def test_column_explanation_considers_all_targeting_mask_policies(model):
    modified, _ = _model_with_noncovering_mask_first(model)

    table_verdict = evaluate(modified, "sp_alice", TABLE)
    column_verdict = evaluate_column(modified, "sp_alice", COLUMN)
    table_column = next(
        column for column in table_verdict.columns if column.column == "customer_email"
    )

    assert table_column.masked
    assert column_verdict.masked
    assert column_verdict.policy_name == "mask_pii"


def test_column_graph_does_not_claim_noncovered_principal_is_in_to(model):
    modified, policy_id = _model_with_noncovering_mask_first(model)
    modified.fgac_matches = [
        match for match in modified.fgac_matches if match.policy_id == policy_id
    ]
    graph = build_column_chain_graph(modified, "sp_alice", COLUMN)

    policy_edges = [edge for edge in graph.edges if edge.target == policy_id]
    assert policy_edges
    assert all(edge.label != "in 'to'" for edge in policy_edges)
    assert any(edge.label == "not in 'to'" for edge in policy_edges)


def test_column_explanation_and_graph_include_using_arguments():
    argument_model = load_dump_model(POLICY_ARGUMENTS_FIXTURE)
    column = "arguments.sales.complete.email"

    explanation = evaluate_column(argument_model, "direct_sp", column)
    graph = build_column_chain_graph(argument_model, "direct_sp", column)

    assert explanation.masked
    assert [argument.matched_columns for argument in explanation.arguments[:2]] == [
        ("email",),
        ("region",),
    ]
    assert [argument.constant_type for argument in explanation.arguments[2:]] == [
        "string",
        "bool",
        "int",
        "float",
        # The dump renders dates and timestamps as quoted strings, like text constants.
        "string",
        "string",
    ]
    assert any(node.id == "arguments.sales.complete.region" for node in graph.nodes)
    assert not any(
        node.id == "arguments.sales.complete.alternate_email" for node in graph.nodes
    )
    assert sum(node.kind == "constant" for node in graph.nodes) == 6
    assert any(edge.label == "USES region_column" for edge in graph.edges)
    assert sum(edge.kind == "argument" for edge in graph.edges) == 7
