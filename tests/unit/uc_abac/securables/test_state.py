from __future__ import annotations

import pytest

from uc_abac.securables import targets_nonexistent_securable
from uc_abac.types import SecurableType


@pytest.mark.parametrize(
    ("missing", "target"),
    [
        ((SecurableType.CATALOG, "cat"), (SecurableType.CATALOG, "cat")),
        ((SecurableType.CATALOG, "cat"), (SecurableType.SCHEMA, "cat.sch")),
        ((SecurableType.CATALOG, "cat"), (SecurableType.TABLE, "cat.sch.tbl")),
        ((SecurableType.CATALOG, "cat"), (SecurableType.VOLUME, "cat.sch.vol")),
        ((SecurableType.CATALOG, "cat"), (SecurableType.FUNCTION, "cat.sch.fn")),
        ((SecurableType.CATALOG, "cat"), (SecurableType.COLUMN, "cat.sch.tbl.col")),
        ((SecurableType.SCHEMA, "cat.sch"), (SecurableType.SCHEMA, "cat.sch")),
        ((SecurableType.SCHEMA, "cat.sch"), (SecurableType.TABLE, "cat.sch.tbl")),
        ((SecurableType.SCHEMA, "cat.sch"), (SecurableType.VOLUME, "cat.sch.vol")),
        ((SecurableType.SCHEMA, "cat.sch"), (SecurableType.FUNCTION, "cat.sch.fn")),
        ((SecurableType.SCHEMA, "cat.sch"), (SecurableType.COLUMN, "cat.sch.tbl.col")),
        ((SecurableType.TABLE, "cat.sch.tbl"), (SecurableType.TABLE, "cat.sch.tbl")),
        (
            (SecurableType.TABLE, "cat.sch.tbl"),
            (SecurableType.COLUMN, "cat.sch.tbl.col"),
        ),
        ((SecurableType.VOLUME, "cat.sch.vol"), (SecurableType.VOLUME, "cat.sch.vol")),
        (
            (SecurableType.COLUMN, "cat.sch.tbl.col"),
            (SecurableType.COLUMN, "cat.sch.tbl.col"),
        ),
    ],
)
def test_securable_state_targets_nonexistent_securable_for_exact_identity_or_descendant(
    missing, target
):
    assert targets_nonexistent_securable(*target, frozenset({missing})) is True


@pytest.mark.parametrize(
    ("missing", "target"),
    [
        ((SecurableType.CATALOG, "cat"), (SecurableType.CATALOG, "catalog")),
        ((SecurableType.CATALOG, "cat"), (SecurableType.SCHEMA, "catalog.sch")),
        ((SecurableType.SCHEMA, "cat.sch"), (SecurableType.SCHEMA, "cat.schema")),
        ((SecurableType.SCHEMA, "cat.sch"), (SecurableType.TABLE, "cat.schema.tbl")),
        ((SecurableType.TABLE, "cat.sch.tbl"), (SecurableType.TABLE, "cat.sch.table")),
        ((SecurableType.VOLUME, "cat.sch.vol"), (SecurableType.TABLE, "cat.sch.vol")),
        (
            (SecurableType.VOLUME, "cat.sch.vol"),
            (SecurableType.TABLE, "cat.sch.vol_table"),
        ),
        ((SecurableType.TABLE, "cat.sch.tbl"), (SecurableType.VOLUME, "cat.sch.tbl")),
    ],
)
def test_securable_state_does_not_target_siblings_prefix_collisions_or_other_types(
    missing, target
):
    assert targets_nonexistent_securable(*target, frozenset({missing})) is False


def test_securable_state_does_not_treat_absent_function_as_nonexistent_securable():
    assert (
        targets_nonexistent_securable(
            SecurableType.FUNCTION,
            "cat.sch.fn",
            frozenset(),
        )
        is False
    )
