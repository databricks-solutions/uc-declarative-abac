"""The principals list classifies each principal from the dump's ``principal_type``."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from abac_viewer.backend.engine.dump import (
    InMemoryDumpReader,
    load_factored_model_from_dump,
)
from abac_viewer.backend.models import PrincipalOut
from abac_viewer.backend.router import list_principals
from tests.unit.abac_viewer.dump_fixtures import dump_rows_from_config

NESTED = Path(__file__).parent / "fixtures" / "nested"

Rows = dict[str, list[dict[str, Any]]]


def _principal_row(template: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """A copy of ``template`` (a ``principals`` row) with ``changes`` applied."""
    return {**deepcopy(template), **changes}


def _member_row(group: str, member: str, member_type: str) -> dict[str, Any]:
    return {
        "config_file_path": None,
        "member_id": None,
        "group_id": None,
        "group_display_name": group,
        "member_display_name": member,
        "member_type": member_type,
    }


def _row(rows: Rows, table: str, **match: Any) -> dict[str, Any]:
    found = [r for r in rows[table] if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, f"expected one {table} row matching {match}"
    return found[0]


def _rows_with_service_principal_and_user() -> Rows:
    """The nested dump plus a service principal whose name has no ``sp`` token, and a
    user whose name does, both members of ``analysts``."""
    rows = dump_rows_from_config(NESTED)
    sp_template = _row(rows, "principals", display_name="sp_alice")
    service_principal = _principal_row(
        sp_template,
        display_name="etl-pipeline",
        principal_type="SERVICE_PRINCIPAL",
        email=None,
        application_id="6f1c0e2a-3b4d-5e6f-8a9b-0c1d2e3f4a5b",
    )
    user = _principal_row(sp_template, display_name="sp_reviewer", email="sp_reviewer")
    rows["principals"] = [*rows["principals"], service_principal, user]
    rows["group_members"] = [
        *rows["group_members"],
        _member_row("analysts", "etl-pipeline", "SERVICE_PRINCIPAL"),
        _member_row("analysts", "sp_reviewer", "USER"),
    ]
    return rows


def _kinds(principals: list[PrincipalOut]) -> dict[str, str]:
    return {p.name: p.kind for p in principals}


# ---------------------------------------------------------------------------
# principal kind
# ---------------------------------------------------------------------------


def test_router_principals_classifies_service_principal_from_principal_type():
    model = load_factored_model_from_dump(
        InMemoryDumpReader(_rows_with_service_principal_and_user())
    )

    kinds = _kinds(list_principals(model))

    assert kinds["etl-pipeline"] == "service_principal"


def test_router_principals_classifies_user_with_sp_token_as_user():
    model = load_factored_model_from_dump(
        InMemoryDumpReader(_rows_with_service_principal_and_user())
    )

    kinds = _kinds(list_principals(model))

    assert kinds["sp_reviewer"] == "user"
