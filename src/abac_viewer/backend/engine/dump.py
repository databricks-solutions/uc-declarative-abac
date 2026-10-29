"""Build a FactoredModel from the tables ``uc-abac dump`` writes.

The viewer explains *deployed* state: it reads the snapshot tables ``uc-abac dump``
writes into a target schema (see ``uc_abac.dumper.TABLE_SPECS`` for their columns)
through a ``DumpReader``, and derives the same factored relations the verdict and chain
engines consume.

Sources, per relation:

- **Securables** — ``securables`` (catalogs, schemas, tables, volumes, functions); a
  table's ``columns`` array becomes one column securable per entry (data type unknown).
  ``function_definitions`` come from a function's ``routine_definition``.
- **Tags** — ``securable_tags``, including column tags. A tag whose value is outside its
  governed tag's allowed values is dropped with a warning (UC would reject it).
- **Governed tags** — ``governed_tags`` (``tag_key`` → ``values``).
- **Groups and membership** — ``group_members`` (direct members, by display name); the
  transitive closure is computed here, breaking cycles with a warning.
- **Mask/filter policies** — ``abac_policies``. ``when_condition`` and ``match_columns``
  are parsed with ``conditions``; for a mask the ``on_column`` alias is ordered first
  (it identifies the masked column). ``using_columns`` entries that name a match alias
  become alias arguments; anything else is a constant (SQL literal) argument. A
  policy's ``to`` defaults to ``account users`` when empty. Each policy is matched
  against the actual tags to produce ``fgac_matches``.
- **Grant policies** — ``pseudo_policies`` (only the active ones are dumped).
  Privileges are normalised to the engine's lower-snake spelling (``USE CATALOG`` →
  ``use_catalog``; abstractions such as ``READ`` stay ``read``).
- **Grants** — ``securable_privileges``, the privileges Unity Catalog actually holds.
  Each actual privilege is attributed by re-matching every grant policy against the
  actual tags (same expansion and USE CATALOG / USE SCHEMA cascade as the engine's
  privileges compiler). An actual privilege some policy produces yields that policy's
  ``GrantMatch`` rows (one per witness). An actual privilege no policy produces yields
  a ``GrantMatch`` against a synthetic ``CompiledGrantPolicy`` with ``origin="direct"``
  (id ``direct:<principal>:<securable>``, name ``manual grant``), so a manual GRANT is
  still explained. A policy match with no actual privilege is ``drift``: recorded on
  the model only (``FactoredModel.drift``) and never counted as access.

Principals: the tables carry canonical identifiers (a service principal's application
id), while the viewer shows display names. Every principal-valued field is mapped to
its display name through the ``principals`` table (identifiers not found there pass
through unchanged). Provenance is the row's ``config_file_path`` (file only; no line).

A condition with unsupported parts (see ``conditions``) never matches and is reported
as a warning, as is an unparseable condition (the policy is then skipped).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from abac_viewer.backend.engine.dump_policies import (
    ParsedFgacPolicy,
    ParsedGrantPolicy,
    parse_fgac_policies,
    parse_grant_policies,
    referenced_keys,
)
from abac_viewer.backend.engine.dump_rows import (
    DumpRow,
    full_name,
    is_known_privilege,
    is_known_securable_type,
    parent_full_name,
    principal_names,
    privilege_key,
    provenance_of,
)
from abac_viewer.backend.engine.matching import (
    ActualPrivilege,
    index_columns,
    match_fgac_policy,
    match_grant_policy,
    reconcile_grants,
)
from abac_viewer.backend.engine.model import (
    CompiledGrantPolicy,
    FactoredModel,
    FgacMatch,
    MembershipEdge,
    Provenance,
    Securable,
    TagAssignment,
)

DUMP_TABLES: tuple[str, ...] = (
    "securables",
    "securable_tags",
    "securable_privileges",
    "abac_policies",
    "pseudo_policies",
    "governed_tags",
    "principals",
    "group_members",
)
"""The dump tables the viewer reads."""


class DumpReadError(RuntimeError):
    """A dump table could not be read."""


class DumpReader(Protocol):
    """Reads one dump table's rows. Array columns are Python sequences of strings."""

    @property
    def source(self) -> str:
        """A label for where the rows come from, e.g. ``catalog.schema``."""
        ...

    def read(self, table: str) -> Sequence[DumpRow]:
        """All rows of ``table``; raises ``DumpReadError`` when it can't be read."""
        ...


@dataclass(frozen=True)
class InMemoryDumpReader:
    """A ``DumpReader`` over rows already in memory (tests, local experiments).

    A table missing from ``tables`` raises ``DumpReadError``, as a missing table would.
    """

    tables: Mapping[str, Sequence[DumpRow]] = field(default_factory=dict)
    source: str = "in-memory"

    def read(self, table: str) -> Sequence[DumpRow]:
        if table not in self.tables:
            raise DumpReadError(f"{table} is not in {self.source}")
        return self.tables[table]


# ---------------------------------------------------------------------------
# revision
# ---------------------------------------------------------------------------


def _revision(rows: Mapping[str, Sequence[DumpRow]]) -> str:
    """A short hash of every row read, stable for identical rows."""
    payload = json.dumps(
        {table: list(rows[table]) for table in DUMP_TABLES},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# securables, functions, and tags
# ---------------------------------------------------------------------------


def _securables_from_row(row: DumpRow) -> list[Securable]:
    """A securables row as its securable, plus one column securable per table column."""
    kind = row["securable_type"]
    name = full_name(row, kind)
    provenance = provenance_of(row["config_file_path"])
    main = Securable(
        full_name=name,
        securable_type=kind.lower(),
        parent_full_name=parent_full_name(kind, name),
        provenance=provenance,
        comment=row["comment"],
    )
    columns = [
        Securable(
            full_name=f"{name}.{column}",
            securable_type="column",
            parent_full_name=name,
            provenance=provenance,
        )
        for column in (row["columns"] or ())
    ]
    return [main, *columns]


def _securables(rows: Sequence[DumpRow]) -> dict[str, Securable]:
    return {s.full_name: s for row in rows for s in _securables_from_row(row)}


def _function_definitions(rows: Sequence[DumpRow]) -> dict[str, str]:
    return {
        full_name(row, "FUNCTION"): row["routine_definition"]
        for row in rows
        if row["securable_type"] == "FUNCTION" and row["routine_definition"] is not None
    }


def _tag_assignments(rows: Sequence[DumpRow]) -> list[TagAssignment]:
    return [
        TagAssignment(
            securable_full_name=full_name(row, row["securable_type"]),
            securable_type=row["securable_type"].lower(),
            tag_name=row["tag_name"],
            tag_value=row["tag_value"],
            provenance=provenance_of(row["config_file_path"]),
        )
        for row in rows
    ]


def _governed_tags(rows: Sequence[DumpRow]) -> dict[str, list[str]]:
    return {row["tag_key"]: list(row["values"] or ()) for row in rows}


def _is_allowed(assignment: TagAssignment, governed: Mapping[str, list[str]]) -> bool:
    allowed = governed.get(assignment.tag_name)
    return not allowed or assignment.tag_value in allowed


def _invalid_tag_warning(assignment: TagAssignment, allowed: list[str]) -> str:
    return (
        f"tag {assignment.tag_name}={assignment.tag_value!r} on "
        f"{assignment.securable_full_name} is outside allowed_values "
        f"{sorted(allowed)!r} and was ignored"
    )


def _valid_tag_assignments(
    assignments: Sequence[TagAssignment], governed: Mapping[str, list[str]]
) -> tuple[list[TagAssignment], list[str]]:
    """Drop tag values outside their governed tag's allowed values, with a warning each."""
    valid = [a for a in assignments if _is_allowed(a, governed)]
    warnings = [
        _invalid_tag_warning(a, governed[a.tag_name])
        for a in assignments
        if not _is_allowed(a, governed)
    ]
    return valid, warnings


def _own_tags(assignments: Iterable[TagAssignment]) -> dict[str, dict[str, str]]:
    by_securable: dict[str, dict[str, str]] = {}
    for assignment in assignments:
        by_securable.setdefault(assignment.securable_full_name, {})[
            assignment.tag_name
        ] = assignment.tag_value
    return by_securable


# ---------------------------------------------------------------------------
# groups and membership closure
# ---------------------------------------------------------------------------


def _service_principals(principal_rows: Sequence[DumpRow]) -> frozenset[str]:
    """The display names the dump records as service principals."""
    return frozenset(
        row["display_name"]
        for row in principal_rows
        if row["principal_type"] == "SERVICE_PRINCIPAL"
    )


def _groups(
    group_rows: Sequence[DumpRow], principal_rows: Sequence[DumpRow]
) -> dict[str, tuple[str, ...]]:
    """Direct members by group display name. Declared groups with no members are kept
    (so they still list as groups), as are groups that only appear as members."""
    members: dict[str, tuple[str, ...]] = {}
    for row in group_rows:
        group = row["group_display_name"]
        members[group] = (*members.get(group, ()), row["member_display_name"])
    declared = [
        row["display_name"]
        for row in principal_rows
        if row["principal_type"] == "GROUP" and row["config_file_path"]
    ]
    return {
        name: members.get(name, ()) for name in dict.fromkeys((*members, *declared))
    }


def _group_provenance(
    principal_rows: Sequence[DumpRow],
) -> dict[str, Provenance | None]:
    """Each declared group's config file, from its ``principals`` row."""
    return {
        row["display_name"]: provenance_of(row["config_file_path"])
        for row in principal_rows
        if row["principal_type"] == "GROUP"
    }


def _ancestor_edges(
    member: str,
    group: str,
    groups: Mapping[str, tuple[str, ...]],
    provenance: Mapping[str, Provenance | None],
    chain: tuple[str, ...] = (),
) -> tuple[tuple[MembershipEdge, ...], tuple[str, ...]]:
    """The membership edges from ``member`` up through ``group``, with cycle warnings.

    ``via`` records the group chain from member to group, innermost first.
    """
    if group in chain:
        cycle = " -> ".join((*chain, group))
        return (), (f"group cycle detected: {cycle}",)
    if group == member:
        cycle = " -> ".join((member, *chain, group))
        return (), (f"group cycle detected: {cycle}",)
    via = (*chain, group)
    edges = (MembershipEdge(member, group, via, provenance.get(group)),)
    warnings: tuple[str, ...] = ()
    for parent, members in groups.items():
        if group in members:
            parent_edges, parent_warnings = _ancestor_edges(
                member, parent, groups, provenance, via
            )
            edges += parent_edges
            warnings += parent_warnings
    return edges, warnings


def _shortest_edges(edges: Iterable[MembershipEdge]) -> list[MembershipEdge]:
    """Keep the shortest via chain per (member, group)."""
    best: dict[tuple[str, str], MembershipEdge] = {}
    for edge in edges:
        key = (edge.member, edge.group)
        if key not in best or len(edge.via) < len(best[key].via):
            best[key] = edge
    return list(best.values())


def _membership_closure(
    groups: Mapping[str, tuple[str, ...]],
    provenance: Mapping[str, Provenance | None],
) -> tuple[list[MembershipEdge], list[str]]:
    """Every member's closure rows across nested groups. Cycles are reported as warnings
    rather than raised: a viewer must render imperfect configs."""
    all_members = sorted({m for members in groups.values() for m in members})
    edges: tuple[MembershipEdge, ...] = ()
    warnings: tuple[str, ...] = ()
    for member in all_members:
        for group, members in groups.items():
            if member in members:
                found, cycles = _ancestor_edges(member, group, groups, provenance)
                edges += found
                warnings += cycles
    return _shortest_edges(edges), list(warnings)


# ---------------------------------------------------------------------------
# governed tag warnings
# ---------------------------------------------------------------------------


def _ungoverned_warnings(
    policy_id: str, keys: Iterable[str], governed: Mapping[str, list[str]]
) -> list[str]:
    """The tool refuses to deploy policies referencing ungoverned tag keys; the viewer
    renders them but warns, so config-in-progress is still explorable."""
    if not governed:
        return []
    return [
        f"policy {policy_id} references ungoverned tag '{key}' "
        f"(the deployer would reject this)"
        for key in sorted(set(keys) - set(governed))
    ]


def _grant_ungoverned(
    parsed: Sequence[ParsedGrantPolicy], governed: Mapping[str, list[str]]
) -> list[str]:
    return [
        w
        for p in parsed
        for w in _ungoverned_warnings(
            p.policy.policy_id, referenced_keys(p.condition), governed
        )
    ]


def _fgac_ungoverned(
    parsed: Sequence[ParsedFgacPolicy], governed: Mapping[str, list[str]]
) -> list[str]:
    warnings: list[str] = []
    for p in parsed:
        keys = set(referenced_keys(p.condition))
        for _alias, condition in p.alias_conditions:
            keys |= referenced_keys(condition)
        warnings += _ungoverned_warnings(p.policy.policy_id, keys, governed)
    return warnings


# ---------------------------------------------------------------------------
# grants (actual privileges)
# ---------------------------------------------------------------------------


def _unknown_privilege_row_warning(row: DumpRow) -> str | None:
    """Why an actual privilege row is skipped (an unknown privilege or securable type,
    e.g. from a newer uc-abac), or None when it is usable."""
    where = f"{row['securable_type']} {row['securable_name']} for {row['grantee']}"
    if not is_known_securable_type(row["securable_type"]):
        return f"skipped privilege on unknown securable type {where}"
    if not is_known_privilege(privilege_key(row["privilege_type"])):
        return f"skipped unknown privilege {row['privilege_type']} on {where}"
    return None


def _actual_privileges(
    rows: Sequence[DumpRow], names: Mapping[str, str]
) -> tuple[tuple[ActualPrivilege, ...], tuple[str, ...]]:
    """The usable actual privileges, and a warning per skipped row."""
    skipped = {id(row): _unknown_privilege_row_warning(row) for row in rows}
    privileges = tuple(
        ActualPrivilege(
            principal=names.get(row["grantee"], row["grantee"]),
            privilege=privilege_key(row["privilege_type"]),
            securable_full_name=full_name(row, row["securable_type"]),
            securable_type=row["securable_type"].lower(),
        )
        for row in rows
        if skipped[id(row)] is None
    )
    return privileges, tuple(w for w in skipped.values() if w is not None)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def _read_tables(reader: DumpReader) -> dict[str, Sequence[DumpRow]]:
    return {table: reader.read(table) for table in DUMP_TABLES}


def load_factored_model_from_dump(reader: DumpReader) -> FactoredModel:
    """Read every table in ``DUMP_TABLES`` and derive the model (see module docstring).

    ``revision`` is a short stable hash of the rows read, so an unchanged dump yields
    the same revision; ``source`` is ``reader.source``.
    """
    rows = _read_tables(reader)
    names = principal_names(rows["principals"])
    governed = _governed_tags(rows["governed_tags"])
    securables = _securables(rows["securables"])
    valid_tags, tag_warnings = _valid_tag_assignments(
        _tag_assignments(rows["securable_tags"]), governed
    )
    groups = _groups(rows["group_members"], rows["principals"])
    membership, cycle_warnings = _membership_closure(
        groups, _group_provenance(rows["principals"])
    )
    grants, grant_parse_warnings = parse_grant_policies(rows["pseudo_policies"], names)
    fgac, fgac_parse_warnings = parse_fgac_policies(rows["abac_policies"], names)
    tags_by_securable = _own_tags(valid_tags)
    grant_matches = [
        m
        for parsed in grants
        for m in match_grant_policy(parsed, securables, tags_by_securable)
    ]
    actual, privilege_warnings = _actual_privileges(rows["securable_privileges"], names)
    reconciliation = reconcile_grants(grant_matches, actual)
    columns = index_columns(securables)
    fgac_matches: list[FgacMatch] = [
        m
        for parsed in fgac
        for m in match_fgac_policy(parsed, securables, columns, tags_by_securable)
    ]
    grant_policies: dict[str, CompiledGrantPolicy] = {
        p.policy.policy_id: p.policy for p in grants
    }
    grant_policies.update({p.policy_id: p for p in reconciliation.direct_policies})
    return FactoredModel(
        revision=_revision(rows),
        source=reader.source,
        securables=securables,
        tag_assignments=valid_tags,
        membership_closure=membership,
        grant_policies=grant_policies,
        fgac_policies={p.policy.policy_id: p.policy for p in fgac},
        grant_matches=list(reconciliation.grant_matches),
        fgac_matches=fgac_matches,
        governed_tags=governed,
        groups=groups,
        service_principals=_service_principals(rows["principals"]),
        function_definitions=_function_definitions(rows["securables"]),
        drift=list(reconciliation.drift),
        warnings=[
            *tag_warnings,
            *cycle_warnings,
            *grant_parse_warnings,
            *fgac_parse_warnings,
            *privilege_warnings,
            *_grant_ungoverned(grants, governed),
            *_fgac_ungoverned(fgac, governed),
        ],
    )
