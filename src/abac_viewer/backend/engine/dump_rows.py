"""Row-level helpers shared by the dump loader.

Dump rows name securables by ``information_schema``-style parts (catalog, schema, and
name, with ``table_name`` for a column) and principals by canonical identifier. These
helpers rebuild dot-delimited UC names, map identifiers to the display names the viewer
shows, and attach provenance from a row's ``config_file_path``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from abac_viewer.backend.engine.model import Provenance
from uc_abac.types import AbstractedPrivilegeType, PrivilegeType, SecurableType

_KNOWN_PRIVILEGES = frozenset(p.value for p in PrivilegeType) | frozenset(
    p.value for p in AbstractedPrivilegeType
)
_KNOWN_SECURABLE_TYPES = frozenset(t.value for t in SecurableType)

DumpRow = Mapping[str, Any]

_CATALOG = "CATALOG"
_SCHEMA = "SCHEMA"
_COLUMN = "COLUMN"


def full_name(row: DumpRow, securable_type: str) -> str:
    """The dot-delimited UC name of the securable a row describes.

    ``securable_type`` is the row's type column (dump spelling, e.g. ``TABLE``), which
    differs by table: ``on_securable_type`` for policies, ``securable_type`` elsewhere.
    A catalog's name is its own name; a column's name is ``catalog.schema.table.column``.
    """
    catalog, schema, name = (
        row["catalog_name"],
        row["schema_name"],
        row["securable_name"],
    )
    if securable_type == _CATALOG:
        return name
    if securable_type == _SCHEMA:
        return f"{catalog}.{name}"
    if securable_type == _COLUMN:
        return f"{catalog}.{schema}.{row['table_name']}.{name}"
    return f"{catalog}.{schema}.{name}"


def parent_full_name(securable_type: str, full: str) -> str | None:
    """The full name of a non-catalog securable's parent (``None`` for a catalog)."""
    return None if securable_type == _CATALOG else full.rsplit(".", 1)[0]


def provenance_of(config_file_path: str | None) -> Provenance | None:
    """Provenance for a row declared in config; the dump records the file only."""
    return Provenance(file=config_file_path) if config_file_path else None


def privilege_key(privilege: str) -> str:
    """Engine spelling of a privilege, e.g. ``USE CATALOG`` -> ``use_catalog``.

    Grant policies store abstractions (``READ``, ``USE``) the same way, so both sides
    compare equal.
    """
    return privilege.lower().replace(" ", "_")


def principal_identifier(principal_row: DumpRow) -> str:
    """The canonical identifier of a ``principals`` row: its email for a user, its
    application id for a service principal, otherwise its display name (a group)."""
    return (
        principal_row["email"]
        or principal_row["application_id"]
        or principal_row["display_name"]
    )


def principal_names(principal_rows: Sequence[DumpRow]) -> dict[str, str]:
    """Canonical identifier → display name for every principal in the dump."""
    return {principal_identifier(row): row["display_name"] for row in principal_rows}


def display_names(
    identifiers: Sequence[str] | None, names: Mapping[str, str]
) -> tuple[str, ...]:
    """Map identifiers to display names; an identifier not in ``names`` passes through."""
    return tuple(names.get(identifier, identifier) for identifier in identifiers or ())


def is_known_privilege(privilege_key_value: str) -> bool:
    """Whether a privilege (engine spelling) is one this uc_abac version knows: a UC
    privilege or a grant-policy abstraction. A dump written by a newer uc-abac may
    carry others, which the viewer skips with a warning rather than failing to load."""
    return privilege_key_value in _KNOWN_PRIVILEGES


def is_known_securable_type(securable_type: str) -> bool:
    """Whether a securable type (any case) is one this uc_abac version knows."""
    return securable_type.upper() in _KNOWN_SECURABLE_TYPES
