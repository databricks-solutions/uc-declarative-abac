"""Dump-loader tests: the viewer model derived from the tables ``uc-abac dump`` writes.

Parity with the YAML loader is covered by the engine tests; these tests cover what is
specific to reading dump rows: the reader contract, revisions, service principals,
manual grants, drift, attribution, unsupported conditions, mask and argument shapes,
and membership closure. Each base table set comes from ``dump_fixtures`` (the rows a
matching deployment would write) and is modified with copies, never in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from abac_viewer.backend.engine.chain_graph import build_chain_graph
from abac_viewer.backend.engine.dump import (
    DUMP_TABLES,
    DumpReadError,
    InMemoryDumpReader,
    load_factored_model_from_dump,
)
from abac_viewer.backend.engine.model import FactoredModel
from abac_viewer.backend.engine.verdict import evaluate
from tests.unit.abac_viewer.dump_fixtures import (
    application_id,
    dump_rows_from_config,
    load_dump_model,
)

FIXTURES = Path(__file__).parent / "fixtures"
NESTED = FIXTURES / "nested"
DIRECT = FIXTURES / "direct_principals"
POLICY_ARGUMENTS = FIXTURES / "policy_arguments"

Rows = dict[str, list[dict[str, Any]]]


# --- helpers (copy-based; the base rows are never mutated) -------------------


def _load(rows: Rows, source: str = "in-memory") -> FactoredModel:
    return load_factored_model_from_dump(InMemoryDumpReader(tables=rows, source=source))


def _matching(rows: Rows, table: str, **match: Any) -> list[dict[str, Any]]:
    return [r for r in rows[table] if all(r.get(k) == v for k, v in match.items())]


def _row(rows: Rows, table: str, **match: Any) -> dict[str, Any]:
    found = _matching(rows, table, **match)
    assert len(found) == 1, f"expected one {table} row matching {match}"
    return found[0]


def _update_row(rows: Rows, table: str, match: dict[str, Any], **changes: Any) -> Rows:
    target = _row(rows, table, **match)
    updated = [{**r, **changes} if r is target else r for r in rows[table]]
    return {**rows, table: updated}


def _drop_row(rows: Rows, table: str, **match: Any) -> Rows:
    target = _row(rows, table, **match)
    return {**rows, table: [r for r in rows[table] if r is not target]}


def _add_row(rows: Rows, table: str, row: dict[str, Any]) -> Rows:
    return {**rows, table: [*rows[table], row]}


def _privilege_row(
    grantee: str,
    privilege_type: str,
    securable_type: str,
    catalog: str,
    schema: str | None,
    securable_name: str,
) -> dict[str, Any]:
    return {
        "config_file_path": None,
        "grantee": grantee,
        "grantee_id": None,
        "grantee_type": "USER",
        "catalog_name": catalog,
        "schema_name": schema,
        "securable_name": securable_name,
        "securable_type": securable_type,
        "privilege_type": privilege_type,
    }


def _policy_matches(model: FactoredModel, name: str) -> list:
    return [m for m in model.fgac_matches if m.policy_id.split("#")[-1] == name]


def _principal_values(model: FactoredModel) -> set[str]:
    """Every principal-valued string the model carries."""
    values = {e.member for e in model.membership_closure}
    values |= {e.group for e in model.membership_closure}
    values |= {m.principal for m in model.grant_matches}
    values |= {m.principal for m in model.drift}
    for policy in model.grant_policies.values():
        values |= set(policy.to)
    for policy in model.fgac_policies.values():
        values |= set(policy.to) | set(policy.exceptions)
    for members in model.groups.values():
        values |= set(members)
    return values


# --- InMemoryDumpReader ------------------------------------------------------


def test_in_memory_dump_reader_read_returns_rows_for_present_table():
    rows = dump_rows_from_config(NESTED)
    reader = InMemoryDumpReader(tables=rows, source="acme.abac_dump")

    assert list(reader.read("securables")) == rows["securables"]
    assert reader.source == "acme.abac_dump"


def test_in_memory_dump_reader_read_raises_when_table_missing():
    reader = InMemoryDumpReader(tables={"securables": []})

    with pytest.raises(DumpReadError):
        reader.read("group_members")


# --- load_factored_model_from_dump: reader contract --------------------------


def test_dump_load_propagates_dump_read_error_when_table_missing():
    rows = dump_rows_from_config(NESTED)
    partial = {t: rows[t] for t in DUMP_TABLES if t != "group_members"}

    with pytest.raises(DumpReadError):
        _load(partial)


# --- source and revision -----------------------------------------------------


def test_dump_model_source_is_reader_source():
    model = _load(dump_rows_from_config(NESTED), source="acme.abac_dump")

    assert model.source == "acme.abac_dump"


def test_dump_model_revision_is_stable_for_identical_rows():
    first = _load(dump_rows_from_config(NESTED))
    second = _load(dump_rows_from_config(NESTED))

    assert first.revision
    assert first.revision == second.revision


def test_dump_model_revision_changes_when_row_changes():
    rows = dump_rows_from_config(NESTED)
    changed = _update_row(
        rows,
        "securable_tags",
        {"securable_name": "orders", "tag_name": "zone"},
        tag_value="silver",
    )

    assert _load(changed).revision != _load(rows).revision


# --- service principals ------------------------------------------------------


def test_dump_service_principal_fields_use_display_names():
    rows = dump_rows_from_config(DIRECT, service_principals=["direct_sp"])
    model = _load(rows)

    values = _principal_values(model)
    assert "direct_sp" in values
    assert application_id("direct_sp") not in values


def test_dump_service_principal_verdicts_match_without_simulation():
    with_sp = _load(dump_rows_from_config(DIRECT, service_principals=["direct_sp"]))
    without_sp = _load(dump_rows_from_config(DIRECT))
    table = "direct.sales.customers"

    simulated = evaluate(with_sp, "direct_sp", table)
    plain = evaluate(without_sp, "direct_sp", table)

    assert simulated.can_read
    assert simulated.can_read == plain.can_read
    assert simulated.row_filtered == plain.row_filtered
    assert simulated.missing == plain.missing
    assert simulated.status == plain.status


# --- manual grants -----------------------------------------------------------


def _rows_with_manual_grants() -> Rows:
    rows = dump_rows_from_config(NESTED)
    rows = _add_row(
        rows,
        "securable_privileges",
        _privilege_row("manual_user", "USE CATALOG", "CATALOG", "acme", None, "acme"),
    )
    rows = _add_row(
        rows,
        "securable_privileges",
        _privilege_row("manual_user", "USE SCHEMA", "SCHEMA", "acme", "sales", "sales"),
    )
    return _add_row(
        rows,
        "securable_privileges",
        _privilege_row("manual_user", "SELECT", "TABLE", "acme", "sales", "orders"),
    )


def test_dump_direct_grant_has_direct_policy_and_grant_match():
    model = _load(_rows_with_manual_grants())

    direct_ids = {
        p.policy_id for p in model.grant_policies.values() if p.origin == "direct"
    }
    matches = [
        m
        for m in model.grant_matches
        if m.principal == "manual_user"
        and m.privilege == "select"
        and m.securable_full_name == "acme.sales.orders"
    ]

    assert direct_ids
    assert matches
    assert all(m.policy_id in direct_ids for m in matches)


def test_dump_direct_grant_makes_manual_user_readable():
    model = _load(_rows_with_manual_grants())

    verdict = evaluate(model, "manual_user", "acme.sales.orders")

    assert verdict.can_read
    assert verdict.missing == []


def test_dump_direct_grant_chain_is_labelled_as_a_direct_grant_not_a_policy():
    model = _load(_rows_with_manual_grants())

    verdict = evaluate(model, "manual_user", "acme.sales.orders")
    grant_chains = [chain for chain in verdict.chains if chain[-1].kind == "grant"]
    policy_nodes = [n for chain in grant_chains for n in chain if n.kind == "policy"]
    graph = build_chain_graph(model, "manual_user", "acme.sales.orders")
    graph_policies = [n for n in graph.nodes if n.id.startswith("direct:")]

    assert policy_nodes
    assert all(n.label == "manual grant" for n in policy_nodes)
    assert all("not produced by a grant policy" in n.detail for n in policy_nodes)
    assert graph_policies
    assert all(n.sublabel == "manual grant" for n in graph_policies)


# --- drift -------------------------------------------------------------------


def _rows_missing_analyst_select() -> Rows:
    return _drop_row(
        dump_rows_from_config(NESTED),
        "securable_privileges",
        grantee="analysts",
        securable_name="orders",
        privilege_type="SELECT",
    )


def test_dump_missing_grant_privilege_is_reported_as_drift():
    model = _load(_rows_missing_analyst_select())

    drift = [
        d
        for d in model.drift
        if d.policy_id == "acme#grant_gold_read"
        and d.securable_full_name == "acme.sales.orders"
        and d.privilege == "select"
    ]

    assert len(drift) == 1
    assert drift[0].principal == "analysts"


def test_dump_missing_grant_privilege_is_drift_and_grants_no_access():
    model = _load(_rows_missing_analyst_select())

    assert any(d.policy_id == "acme#grant_gold_read" for d in model.drift)
    verdict = evaluate(model, "sp_alice", "acme.sales.orders")
    assert not verdict.can_read
    assert "select" in verdict.missing


# --- attribution -------------------------------------------------------------


def test_dump_every_grant_match_is_attributed_to_a_policy_when_nothing_drifted():
    model = _load(dump_rows_from_config(NESTED))

    assert model.grant_matches
    for match in model.grant_matches:
        assert model.grant_policies[match.policy_id].origin == "policy"
    assert model.drift == []


# --- unsupported and unparseable conditions ----------------------------------


def test_dump_unsupported_condition_never_matches_and_warns():
    rows = _update_row(
        dump_rows_from_config(NESTED),
        "abac_policies",
        {"policy_name": "mask_pii"},
        when_condition=(
            "has_tag_value('zone', 'gold') AND has_context_attribute_value('k', 'v')"
        ),
    )
    model = _load(rows)

    assert _policy_matches(model, "mask_pii") == []
    assert any("mask_pii" in w for w in model.warnings)


def test_dump_unparseable_condition_skips_policy_and_warns_without_raising():
    rows = _update_row(
        dump_rows_from_config(NESTED),
        "abac_policies",
        {"policy_name": "mask_pii"},
        when_condition="has_tag(",
    )
    model = _load(rows)

    assert _policy_matches(model, "mask_pii") == []
    assert any("mask_pii" in w for w in model.warnings)


# --- mask ordering -----------------------------------------------------------


def test_dump_mask_match_columns_puts_on_column_alias_first():
    rows = dump_rows_from_config(POLICY_ARGUMENTS)
    original = _row(rows, "abac_policies", policy_name="mask_with_arguments")
    rows = _update_row(
        rows,
        "abac_policies",
        {"policy_name": "mask_with_arguments"},
        match_columns=tuple(reversed(original["match_columns"])),
    )
    model = _load(rows)

    policy = next(
        p for p in model.fgac_policies.values() if p.name == "mask_with_arguments"
    )
    assert policy.match_columns[0][0] == original["on_column"]


# --- using_columns arguments -------------------------------------------------


def _mask_arguments(model: FactoredModel) -> tuple:
    policy = next(
        p for p in model.fgac_policies.values() if p.name == "mask_with_arguments"
    )
    return policy.column_arguments


def test_dump_using_columns_alias_becomes_alias_argument():
    arguments = _mask_arguments(_load(dump_rows_from_config(POLICY_ARGUMENTS)))

    assert any(a.kind == "alias" and a.alias == "region_column" for a in arguments)


def test_dump_using_columns_quoted_literal_becomes_string_constant():
    arguments = _mask_arguments(_load(dump_rows_from_config(POLICY_ARGUMENTS)))

    assert any(
        a.kind == "constant"
        and a.constant == "REDACTED"
        and a.constant_type == "string"
        for a in arguments
    )


def test_dump_using_columns_number_becomes_int_constant():
    arguments = _mask_arguments(_load(dump_rows_from_config(POLICY_ARGUMENTS)))

    assert any(
        a.kind == "constant"
        and a.constant_type == "int"
        and a.constant == 7
        and not isinstance(a.constant, bool)
        for a in arguments
    )


def test_dump_using_columns_true_becomes_bool_constant():
    arguments = _mask_arguments(_load(dump_rows_from_config(POLICY_ARGUMENTS)))

    assert any(
        a.kind == "constant" and a.constant_type == "bool" and a.constant is True
        for a in arguments
    )


# --- policy principals -------------------------------------------------------


def test_dump_policy_empty_to_principals_defaults_to_account_users():
    rows = _update_row(
        dump_rows_from_config(NESTED),
        "abac_policies",
        {"policy_name": "mask_pii"},
        to_principals=(),
        to_principal_ids=(),
    )
    model = _load(rows)

    policy = next(p for p in model.fgac_policies.values() if p.name == "mask_pii")
    assert policy.to == ("account users",)


# --- membership closure ------------------------------------------------------


def test_dump_group_closure_is_transitive_across_nested_groups():
    rows = _add_row(
        dump_rows_from_config(NESTED),
        "group_members",
        {
            "member_id": None,
            "group_id": None,
            "group_display_name": "data_platform",
            "member_display_name": "analysts",
            "member_type": "GROUP",
        },
    )
    model = _load(rows)

    assert {"analysts_emea", "analysts", "data_platform"} <= model.groups_of("sp_alice")


def test_dump_membership_cycle_warns_without_raising():
    rows = _add_row(
        dump_rows_from_config(NESTED),
        "group_members",
        {
            "member_id": None,
            "group_id": None,
            "group_display_name": "analysts_emea",
            "member_display_name": "analysts",
            "member_type": "GROUP",
        },
    )
    model = _load(rows)

    assert "analysts" in model.groups_of("sp_alice")
    assert any("cycle" in w.lower() for w in model.warnings)


def test_dump_membership_cycle_does_not_make_a_group_its_own_member():
    rows = _add_row(
        dump_rows_from_config(NESTED),
        "group_members",
        {
            "member_id": None,
            "group_id": None,
            "group_display_name": "analysts_emea",
            "member_display_name": "analysts",
            "member_type": "GROUP",
        },
    )
    model = _load(rows)

    assert "analysts" not in model.groups_of("analysts")
    assert "analysts_emea" not in model.groups_of("analysts_emea")
    assert any("cycle" in w.lower() for w in model.warnings)


# --- ALL PRIVILEGES ------------------------------------------------------------


def _rows_with_all_privileges(securable_type, catalog, schema, name) -> Rows:
    rows = dump_rows_from_config(NESTED)
    return _add_row(
        rows,
        "securable_privileges",
        _privilege_row(
            "manual_user", "ALL PRIVILEGES", securable_type, catalog, schema, name
        ),
    )


def test_dump_all_privileges_on_catalog_grants_read_on_its_tables():
    model = _load(_rows_with_all_privileges("CATALOG", "acme", None, "acme"))

    verdict = evaluate(model, "manual_user", "acme.sales.orders")

    assert verdict.can_read
    assert verdict.missing == []


def test_dump_all_privileges_on_table_does_not_grant_use_on_its_parents():
    model = _load(_rows_with_all_privileges("TABLE", "acme", "sales", "orders"))

    verdict = evaluate(model, "manual_user", "acme.sales.orders")

    assert not verdict.can_read
    assert {"use_catalog", "use_schema"} <= set(verdict.missing)
    assert "select" not in verdict.missing


def test_dump_all_privileges_on_schema_grants_use_schema_but_not_use_catalog():
    model = _load(_rows_with_all_privileges("SCHEMA", "acme", "sales", "sales"))

    verdict = evaluate(model, "manual_user", "acme.sales.orders")

    assert verdict.missing == ["use_catalog"]


def test_dump_all_privileges_does_not_cover_other_principals():
    model = _load(_rows_with_all_privileges("CATALOG", "acme", None, "acme"))

    assert not evaluate(model, "nobody_else", "acme.sales.orders").can_read


# --- unknown values ------------------------------------------------------------


def test_dump_unknown_privilege_type_warns_without_failing_load():
    rows = _add_row(
        dump_rows_from_config(NESTED),
        "securable_privileges",
        _privilege_row(
            "manual_user", "SOME FUTURE PRIVILEGE", "TABLE", "acme", "sales", "orders"
        ),
    )

    model = _load(rows)

    assert any(
        "SOME FUTURE PRIVILEGE" in w or "some_future_privilege" in w
        for w in model.warnings
    )
    assert evaluate(model, "sp_alice", "acme.sales.orders").can_read


def test_dump_unknown_securable_type_warns_without_failing_load():
    rows = _add_row(
        dump_rows_from_config(NESTED),
        "securable_privileges",
        _privilege_row(
            "manual_user", "SELECT", "SOME_FUTURE_TYPE", "acme", "sales", "orders"
        ),
    )

    model = _load(rows)

    assert any(
        "SOME_FUTURE_TYPE" in w or "some_future_type" in w for w in model.warnings
    )


def _policy_with_type(policy_type: str | None) -> Rows:
    """The nested fixture with one extra ``abac_policies`` row, a copy of ``mask_pii``
    whose ``policy_type`` is ``policy_type``."""
    rows = dump_rows_from_config(NESTED)
    mask = _row(rows, "abac_policies", policy_name="mask_pii")
    return _add_row(
        rows,
        "abac_policies",
        {**mask, "policy_name": "odd_policy", "policy_type": policy_type},
    )


def test_dump_unknown_policy_type_warns_and_skips_policy_without_failing_load():
    model = _load(_policy_with_type("ROW_ACCESS_RULE"))

    assert "acme#odd_policy" not in model.fgac_policies
    assert "acme#mask_pii" in model.fgac_policies
    assert any(
        "acme#odd_policy" in w and "ROW_ACCESS_RULE" in w for w in model.warnings
    )


def test_dump_null_policy_type_warns_and_skips_policy_without_failing_load():
    model = _load(_policy_with_type(None))

    assert "acme#odd_policy" not in model.fgac_policies
    assert "acme#mask_pii" in model.fgac_policies
    assert any("acme#odd_policy" in w for w in model.warnings)


# --- for: securable type -------------------------------------------------------


def test_dump_grant_policy_for_tables_is_attributed_without_drift():
    model = load_dump_model(FIXTURES / "for_securable_type")

    assert model.drift == []
    assert model.grant_matches
    assert all(
        model.grant_policies[m.policy_id].origin == "policy"
        for m in model.grant_matches
    )
    assert {m.securable_type for m in model.grant_matches} == {"table"}
    assert {m.securable_full_name for m in model.grant_matches} == {"acme.sales.orders"}


def test_dump_unknown_grant_policy_privilege_warns_without_failing_load():
    rows = dump_rows_from_config(NESTED)
    policy = _row(rows, "pseudo_policies", policy_name="grant_gold_read")
    rows = _update_row(
        rows,
        "pseudo_policies",
        {"policy_name": "grant_gold_read"},
        privileges=(*policy["privileges"], "SOME FUTURE PRIVILEGE"),
    )

    model = _load(rows)

    assert any(
        "some_future_privilege" in w.lower().replace(" ", "_") for w in model.warnings
    )
    assert evaluate(model, "sp_alice", "acme.sales.orders").can_read
