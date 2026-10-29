"""The securable tree's per-principal table rollup agrees with the row-filter verdicts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from abac_viewer.backend.engine import row_filter_state_for
from abac_viewer.backend.engine.model import FactoredModel
from abac_viewer.backend.models import TreeNodeOut
from abac_viewer.backend.router import securable_tree
from tests.unit.abac_viewer.dump_fixtures import load_dump_model

FIXTURES = Path(__file__).parent / "fixtures"


def _readable_table_nodes(nodes: list[TreeNodeOut]) -> Iterator[TreeNodeOut]:
    """Every readable table node under ``nodes``, walking ``children`` recursively."""
    for node in nodes:
        if node.securable_type == "table":
            if node.readable:
                yield node
        else:
            yield from _readable_table_nodes(node.children)


def _model(fixture: str) -> FactoredModel:
    return load_dump_model(FIXTURES / fixture)


@pytest.mark.parametrize("fixture", ["nested", "fgac_edge_cases"])
def test_router_tree_row_filter_targeted_matches_verdict_for_every_principal(fixture):
    model = _model(fixture)

    for principal in sorted(model.principals()):
        tree = securable_tree(model, principal)
        for table in _readable_table_nodes(tree):
            expected, _filtered = row_filter_state_for(
                model, principal, table.full_name
            )
            assert table.row_filter_targeted == expected, (
                principal,
                table.full_name,
            )
