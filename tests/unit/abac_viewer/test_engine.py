"""Engine tests over the synthetic nested fixture.

Each model is loaded from a simulated dump of a fixture config (see
``dump_fixtures``): the tables ``uc-abac dump`` would write for a workspace where
the config is fully deployed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abac_viewer.backend.engine.dump import (
    InMemoryDumpReader,
    load_factored_model_from_dump,
)
from abac_viewer.backend.engine.model import FactoredModel, MembershipEdge
from abac_viewer.backend.engine.verdict import (
    evaluate,
    explanation_sentence,
    readable_tables,
    who_can_read,
)
from abac_viewer.backend.router import list_principals, who_can_see
from tests.unit.abac_viewer.dump_fixtures import dump_rows_from_config, load_dump_model

FIXTURE = Path(__file__).parent / "fixtures" / "nested"
DIRECT_PRINCIPALS_FIXTURE = Path(__file__).parent / "fixtures" / "direct_principals"
INVALID_TAG_VALUES_FIXTURE = Path(__file__).parent / "fixtures" / "invalid_tag_values"
DEMO_FIXTURE = Path(__file__).parents[3] / "examples" / "abac_viewer_demo" / "configs"


@pytest.fixture(scope="module")
def model():
    return load_dump_model(FIXTURE)


# --- ingest -----------------------------------------------------------------


def test_ingest_builds_securable_inventory(model):
    assert model.securables["acme"].securable_type == "catalog"
    assert model.securables["acme.sales.orders"].securable_type == "table"
    col = model.securables["acme.sales.orders.customer_email"]
    assert col.securable_type == "column"
    assert col.parent_full_name == "acme.sales.orders"


def test_ingest_membership_closure_flattens_subgroups(model):
    groups_of_alice = {
        e.group for e in model.membership_closure if e.member == "sp_alice"
    }
    assert groups_of_alice == {"analysts_emea", "analysts"}
    # the transitive row keeps its chain for the why-panel
    transitive = next(
        e
        for e in model.membership_closure
        if e.member == "sp_alice" and e.group == "analysts"
    )
    assert transitive.via == ("analysts_emea", "analysts")


def test_ingest_compiles_policies_with_provenance(model):
    grant = model.grant_policies["acme#grant_gold_read"]
    assert grant.has_tags == (("zone", "gold"),)
    assert grant.provenance is not None
    assert grant.provenance.file.endswith("nested/configs.yaml")
    mask = model.fgac_policies["acme#mask_pii"]
    assert mask.exceptions == ("auditors",)
    assert mask.match_column_has_tags == (("pii", "*"),)


def test_ingest_scopes_duplicate_column_provenance_to_its_table_file():
    demo_model = load_dump_model(DEMO_FIXTURE)
    customer_column = demo_model.securables["abac_viz_demo.sales.customers.region"]
    invoice_column = demo_model.securables["abac_viz_demo.finance.invoices.region"]
    assignment = next(
        tag
        for tag in demo_model.tag_assignments
        if tag.securable_full_name == customer_column.full_name
        and tag.tag_name == "abac_demo_filter_col"
    )

    assert customer_column.provenance is not None
    assert customer_column.provenance.file.endswith("sales/tables/customers.yaml")
    assert invoice_column.provenance is not None
    assert invoice_column.provenance.file.endswith("finance/tables/invoices.yaml")
    assert assignment.provenance is not None
    assert assignment.provenance.file.endswith("sales/tables/customers.yaml")


def test_demo_trips_filter_matches_table_and_both_region_inputs():
    demo_model = load_dump_model(DEMO_FIXTURE)
    policy = demo_model.fgac_policies["abac_viz_demo.sales#filter_trips_by_region"]
    match = next(
        match
        for match in demo_model.fgac_matches
        if match.policy_id == policy.policy_id
    )

    assert match.table_full_name == "abac_viz_demo.sales.trips"
    assert match.matched_table_tags == (
        ("abac_demo_sensitivity", "high"),
        ("abac_demo_trips", "trip"),
    )
    assert [alias for alias, _matches in match.matched_aliases] == [
        "from_region",
        "to_region",
    ]
    assert {column for column, _atoms in match.matched_columns} == {
        "from_region",
        "to_region",
    }
    assert evaluate(
        demo_model, "abac_demo_sp_ana_emea_1", "abac_viz_demo.sales.trips"
    ).row_filtered
    assert not evaluate(
        demo_model, "abac_demo_sp_eng_1", "abac_viz_demo.sales.trips"
    ).row_filtered


def test_ingest_grant_matches_carry_policy_attribution(model):
    gold_selects = [
        m
        for m in model.grant_matches
        if m.policy_id == "acme#grant_gold_read" and m.privilege == "select"
    ]
    assert {m.securable_full_name for m in gold_selects} == {
        "acme.sales.orders",
        "acme.hr.employees",
    }
    assert all(m.matched_tags == (("zone", "gold"),) for m in gold_selects)


def test_ingest_matches_tool_compiler_exactly(model):
    """Viewer grant matching == uc_abac.compile_desired_privileges."""
    from uc_abac.configs import (
        ResourcesConfig,
        consolidate_resources,
        discover_yaml_files,
        load_raw_configs,
        resolve_refs,
    )
    from uc_abac.governed_tags import GovernedTag
    from uc_abac.logger import ChangeLogger
    from uc_abac.privileges import compile_desired_privileges
    from uc_abac.tags import compile_desired_tags

    paths = discover_yaml_files(FIXTURE)
    raw_defs, raw_resources = load_raw_configs(paths)
    resolved = resolve_refs(raw_defs, raw_resources, override_strategy="merge")
    config = ResourcesConfig(**consolidate_resources(resolved))
    logger = ChangeLogger()
    governed = {
        GovernedTag(name=n, allowed_values=frozenset(gt.allowed_values))
        for n, gt in (config.governed_tags or {}).items()
    }
    tags = compile_desired_tags(config, governed, logger)
    tool_privileges = compile_desired_privileges(
        config, tags, {g.name for g in governed}, logger
    )

    tool_set = {
        (p.securable_full_name, p.principal.name, p.privilege_type.value)
        for p in tool_privileges
    }
    viewer_set = {
        (m.securable_full_name, m.principal, m.privilege) for m in model.grant_matches
    }
    assert viewer_set == tool_set


# --- verdicts ---------------------------------------------------------------


def test_verdict_subgroup_member_reads_via_catalog_policy(model):
    v = evaluate(model, "sp_alice", "acme.sales.orders")
    assert v.can_read and v.missing == []
    # why-chain includes the transitive membership witness
    memberships = [n for chain in v.chains for n in chain if n.kind == "membership"]
    assert any("analysts_emea" in n.detail for n in memberships)


def test_verdict_masks_pii_column_for_non_excepted(model):
    v = evaluate(model, "sp_alice", "acme.sales.orders")
    masked = {c.column for c in v.columns if c.masked}
    assert masked == {"customer_email"}
    assert v.row_filtered  # analysts hit the gold row filter too


def test_verdict_excepted_group_sees_unmasked(model):
    # auditors are excepted from the mask, but have no grants: no read access,
    # and the mask does not apply to them
    v = evaluate(model, "sp_frank", "acme.sales.orders")
    assert not v.can_read
    assert not any(c.masked for c in v.columns)


def test_verdict_direct_schema_grant_without_filter(model):
    v = evaluate(model, "sp_erin", "acme.sales.orders")
    assert v.can_read  # engineers ⊂ data_platform, tagless schema grant
    assert not v.row_filtered  # the filter targets analysts only
    assert {c.column for c in v.columns if c.masked} == {"customer_email"}


def test_verdict_no_access_outside_granted_scope(model):
    # data_platform's grant is schema-scoped to acme.sales — hr is out of reach
    v = evaluate(model, "sp_erin", "acme.hr.employees")
    assert not v.can_read
    assert v.missing  # deny stays plain: prerequisites listed, no diagnosis


def test_verdict_chain_nodes_link_to_yaml_source(model):
    v = evaluate(model, "sp_alice", "acme.sales.orders")
    policy_nodes = [n for chain in v.chains for n in chain if n.kind == "policy"]
    assert any(n.source and n.source.endswith("configs.yaml") for n in policy_nodes)


# --- inverse + listing queries ----------------------------------------------


def test_who_can_read_aggregates_groups_and_users(model):
    readers = {v.principal for v in who_can_read(model, "acme.sales.orders")}
    assert {"sp_alice", "sp_bob", "sp_carol", "sp_dave", "sp_erin"} <= readers
    assert "sp_frank" not in readers


def test_readable_tables_is_scoped_per_principal(model):
    tables = {v.securable for v in readable_tables(model, "sp_erin") if v.can_read}
    assert tables == {"acme.sales.orders", "acme.sales.leads"}


def test_explanation_sentence_mentions_masking(model):
    v = evaluate(model, "sp_alice", "acme.sales.orders")
    s = explanation_sentence(v)
    assert "sp_alice can read acme.sales.orders" in s
    assert "customer_email" in s


def test_policy_referenced_principals_are_discoverable_without_groups():
    direct_model = load_dump_model(DIRECT_PRINCIPALS_FIXTURE)

    assert {"direct_sp", "direct_viewer"} <= direct_model.users()
    assert {"direct_sp", "direct_viewer", "account users"} <= direct_model.principals()
    assert evaluate(direct_model, "direct_sp", "direct.sales.customers").can_read
    direct_viewer = evaluate(direct_model, "direct_viewer", "direct.sales.customers")
    assert direct_viewer.can_read
    assert not direct_viewer.columns[0].masked
    listed = {principal.name for principal in list_principals(direct_model)}
    visible = {
        row.principal
        for row in who_can_see("direct.sales.customers.email", direct_model)
    }
    assert {"direct_sp", "direct_viewer"} <= listed
    assert {"direct_sp", "direct_viewer"} <= visible


def _tag_row(catalog, schema, table, name, securable_type, tag_name, tag_value):
    return {
        "config_file_path": None,
        "catalog_name": catalog,
        "schema_name": schema,
        "table_name": table,
        "securable_name": name,
        "securable_type": securable_type,
        "tag_name": tag_name,
        "tag_value": tag_value,
    }


def test_invalid_governed_tag_values_are_ignored_before_policy_matching():
    rows = dump_rows_from_config(INVALID_TAG_VALUES_FIXTURE)
    rows["securable_tags"] = [
        _tag_row(
            "invalid", "sales", "customers", "customers", "TABLE", "zone", "silver"
        ),
        _tag_row("invalid", "sales", "customers", "email", "COLUMN", "pii", "phone"),
    ]

    invalid_model = load_factored_model_from_dump(InMemoryDumpReader(rows))

    assert invalid_model.tag_assignments == []
    assert invalid_model.grant_matches == []
    assert invalid_model.fgac_matches == []
    outside = [w for w in invalid_model.warnings if "outside allowed_values" in w]
    assert len(outside) == 2


# --- FactoredModel membership lookups ------------------------------------------


class CountingList(list):
    """A list that counts how many times it has been iterated."""

    def __init__(self, items=()):
        super().__init__(items)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


def _alice_closure() -> CountingList:
    return CountingList(
        [
            MembershipEdge("sp_alice", "analysts_emea", ("analysts_emea",)),
            MembershipEdge("sp_alice", "analysts", ("analysts_emea", "analysts")),
            MembershipEdge("analysts_emea", "analysts", ("analysts",)),
        ]
    )


def test_factored_model_groups_of_returns_transitive_groups():
    model = FactoredModel(revision="r", source="s", membership_closure=_alice_closure())

    assert model.groups_of("sp_alice") == {"analysts_emea", "analysts"}
    assert model.principal_matches("sp_alice", "analysts")
    assert model.principal_matches("sp_alice", "account users")
    assert not model.principal_matches("sp_alice", "engineers")


def test_factored_model_lookups_do_not_rescan_membership_closure():
    closure = _alice_closure()
    model = FactoredModel(revision="r", source="s", membership_closure=closure)
    iterations_after_construction = closure.iterations

    for _ in range(50):
        model.groups_of("sp_alice")
        model.principal_matches("sp_alice", "analysts")

    assert closure.iterations == iterations_after_construction
