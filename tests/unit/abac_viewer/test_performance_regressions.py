"""Algorithmic regression checks for catalog-wide column queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from abac_viewer.backend.engine import verdict
from tests.unit.abac_viewer.dump_fixtures import load_dump_model

FIXTURE = Path(__file__).parent / "fixtures" / "nested"


@pytest.fixture(scope="module")
def model():
    return load_dump_model(FIXTURE)


def test_masked_columns_returns_only_columns_on_readable_tables(model):
    rows = verdict.masked_columns_for(model, "sp_erin")

    assert rows
    assert {row.table_full_name for row in rows} == {
        "acme.sales.leads",
        "acme.sales.orders",
    }


def test_masked_columns_evaluates_grants_at_most_once_per_table(model, monkeypatch):
    original = verdict._grants_for
    calls: list[str] = []

    def counting_grants_for(current_model, principal, table_full_name):
        calls.append(table_full_name)
        return original(current_model, principal, table_full_name)

    monkeypatch.setattr(verdict, "_grants_for", counting_grants_for)

    verdict.masked_columns_for(model, "sp_alice")

    table_count = len(
        {
            securable.parent_full_name
            for securable in model.securables.values()
            if securable.securable_type == "column"
        }
    )
    assert len(calls) <= table_count
