"""Parse the policy rows of a dump into the viewer's compiled policies.

``pseudo_policies`` holds the active grant policies and ``abac_policies`` the mask and
filter policies. Each row's tag predicate is a rendered SQL condition, parsed with
``conditions`` so matching uses the same ``TagCondition`` semantics everywhere. Each
parsed policy keeps its ``TagCondition`` next to the compiled model object, because
matching needs the full predicate (including negated and unsupported parts that the
model does not show).

A condition that cannot be parsed skips its policy with a warning. A condition with
unsupported parts keeps the policy, which never matches, and warns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar

from abac_viewer.backend.engine.conditions import (
    ConditionParseError,
    TagCondition,
    parse_match_column,
    parse_tag_condition,
)
from abac_viewer.backend.engine.dump_rows import (
    DumpRow,
    display_names,
    full_name,
    is_known_privilege,
    privilege_key,
    provenance_of,
)
from abac_viewer.backend.engine.model import (
    ALL_USERS_GROUP,
    CompiledFgacPolicy,
    CompiledGrantPolicy,
    FgacColumnArgument,
)

_FGAC_TYPES = {"COLUMN_MASK": "mask", "ROW_FILTER": "filter"}
_INT = re.compile(r"-?\d+")
_FLOAT = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")

T = TypeVar("T")
ParseResult = tuple[T | None, tuple[str, ...]]


@dataclass(frozen=True)
class ParsedGrantPolicy:
    """A grant policy and the tag predicate that selects its securables."""

    policy: CompiledGrantPolicy
    condition: TagCondition


@dataclass(frozen=True)
class ParsedFgacPolicy:
    """A mask or filter policy, its table predicate, and one predicate per match alias.

    ``alias_conditions`` runs parallel to ``policy.match_columns``.
    """

    policy: CompiledFgacPolicy
    condition: TagCondition
    alias_conditions: tuple[tuple[str, TagCondition], ...]


def referenced_keys(condition: TagCondition) -> frozenset[str]:
    """Every tag key the condition names, positive or negated."""
    atoms = (
        *condition.has_tags,
        *condition.has_any_of_tags,
        *condition.has_none_of_tags,
    )
    return frozenset(key for key, _value in atoms)


# ---------------------------------------------------------------------------
# warnings
# ---------------------------------------------------------------------------


def _unparseable_warning(policy_id: str, error: ConditionParseError) -> str:
    return f"policy {policy_id} has an unparseable condition and was skipped: {error}"


def _unsupported_warnings(label: str, condition: TagCondition) -> tuple[str, ...]:
    """A warning when ``condition`` has parts the viewer cannot evaluate, else none."""
    if not condition.unsupported:
        return ()
    parts = ", ".join(condition.unsupported)
    return (f"policy {label} has an unsupported condition ({parts}); it never matches",)


def _split_results(
    results: Sequence[ParseResult[T]],
) -> tuple[tuple[T, ...], tuple[str, ...]]:
    """Split per-row ``(parsed or None, warnings)`` results into the parsed values and
    the warnings, preserving row order."""
    parsed = tuple(item for item, _warnings in results if item is not None)
    warnings = tuple(w for _item, row_warnings in results for w in row_warnings)
    return parsed, warnings


# ---------------------------------------------------------------------------
# grant policies (pseudo_policies)
# ---------------------------------------------------------------------------


def _grant_privileges(row: DumpRow) -> tuple[str, ...]:
    """The grant policy's privileges in engine spelling, all of them, known or not."""
    return tuple(privilege_key(p) for p in row["privileges"] or ())


def _unknown_privilege_warnings(policy_id: str, row: DumpRow) -> tuple[str, ...]:
    return tuple(
        f"grant policy {policy_id}: skipped unknown privilege {privilege}"
        for privilege in _grant_privileges(row)
        if not is_known_privilege(privilege)
    )


def _grant_policy(
    row: DumpRow, names: Mapping[str, str], parent: str, condition: TagCondition
) -> CompiledGrantPolicy:
    for_type = row["for_securable_type"]
    return CompiledGrantPolicy(
        policy_id=f"{parent}#{row['policy_name']}",
        name=row["policy_name"],
        parent_full_name=parent,
        has_tags=condition.has_tags,
        has_any_of_tags=condition.has_any_of_tags,
        privileges=tuple(p for p in _grant_privileges(row) if is_known_privilege(p)),
        to=display_names(row["to_principals"], names),
        for_securable_type=for_type.lower() if for_type else None,
        expiry_date=None,
        comment=row["comment"],
        provenance=provenance_of(row["config_file_path"]),
    )


def _parse_grant_row(
    row: DumpRow, names: Mapping[str, str]
) -> ParseResult[ParsedGrantPolicy]:
    parent = full_name(row, row["on_securable_type"])
    policy_id = f"{parent}#{row['policy_name']}"
    try:
        condition = parse_tag_condition(row["when_condition"])
    except ConditionParseError as error:
        return None, (_unparseable_warning(policy_id, error),)
    policy = _grant_policy(row, names, parent, condition)
    parsed = ParsedGrantPolicy(policy=policy, condition=condition)
    warnings = _unsupported_warnings(policy_id, condition)
    return parsed, warnings + _unknown_privilege_warnings(policy_id, row)


def parse_grant_policies(
    rows: Sequence[DumpRow], names: Mapping[str, str]
) -> tuple[tuple[ParsedGrantPolicy, ...], tuple[str, ...]]:
    """The grant policies in ``pseudo_policies`` rows, and the warnings raised."""
    return _split_results([_parse_grant_row(row, names) for row in rows])


# ---------------------------------------------------------------------------
# mask and filter policies (abac_policies)
# ---------------------------------------------------------------------------


def _alias_first(
    aliases: tuple[tuple[str, TagCondition], ...], on_column: str | None
) -> tuple[tuple[str, TagCondition], ...]:
    """Order a mask's aliases with the ``on_column`` alias first (it identifies the masked
    column); the other aliases keep their declared order."""
    return tuple(sorted(aliases, key=lambda pair: pair[0] != on_column))


def _parse_constant(token: str) -> tuple[bool | int | float | str, str]:
    """A non-alias ``using_columns`` token as its Python value and type.

    Quoted literals are decoded (a doubled quote is one quote). Dates and timestamps are
    rendered as quoted strings, so they come back as ``string``.
    """
    if token.upper() in ("TRUE", "FALSE"):
        return token.upper() == "TRUE", "bool"
    if _INT.fullmatch(token):
        return int(token), "int"
    if _FLOAT.fullmatch(token):
        return float(token), "float"
    if len(token) >= 2 and token[0] == token[-1] == "'":
        return token[1:-1].replace("''", "'"), "string"
    return token, "string"


def _column_argument(
    token: str, alias_conditions: Mapping[str, TagCondition]
) -> FgacColumnArgument:
    """An alias argument when ``token`` names a match alias, else a constant."""
    if token in alias_conditions:
        condition = alias_conditions[token]
        return FgacColumnArgument(
            kind="alias",
            alias=token,
            has_tags=condition.has_tags,
            has_any_of_tags=condition.has_any_of_tags,
        )
    value, value_type = _parse_constant(token)
    return FgacColumnArgument(kind="constant", constant=value, constant_type=value_type)


def _column_arguments(
    row: DumpRow, policy_type: str, alias_conditions: Mapping[str, TagCondition]
) -> tuple[FgacColumnArgument, ...]:
    """The function's arguments in call order: a mask's masked column (its ``on_column``
    alias) first, then the ``using_columns`` entries."""
    masked = (row["on_column"],) if policy_type == "mask" and row["on_column"] else ()
    tokens = (*masked, *(row["using_columns"] or ()))
    return tuple(_column_argument(token, alias_conditions) for token in tokens)


def _fgac_policy(
    row: DumpRow,
    names: Mapping[str, str],
    parent: str,
    condition: TagCondition,
    aliases: tuple[tuple[str, TagCondition], ...],
) -> CompiledFgacPolicy:
    policy_type = _FGAC_TYPES[row["policy_type"]]
    first = aliases[0][1] if policy_type == "mask" and aliases else None
    alias_conditions = dict(aliases)
    return CompiledFgacPolicy(
        policy_id=f"{parent}#{row['policy_name']}",
        name=row["policy_name"],
        policy_type=policy_type,
        parent_full_name=parent,
        has_tags=condition.has_tags,
        has_any_of_tags=condition.has_any_of_tags,
        function=row["function_full_name"],
        to=display_names(row["to_principals"], names) or (ALL_USERS_GROUP,),
        exceptions=display_names(row["except_principals"], names),
        column_arguments=_column_arguments(row, policy_type, alias_conditions),
        match_columns=tuple(
            (alias, cond.has_tags, cond.has_any_of_tags) for alias, cond in aliases
        ),
        match_column_has_tags=first.has_tags if first else (),
        match_column_has_any_of_tags=first.has_any_of_tags if first else (),
        comment=row["comment"],
        provenance=provenance_of(row["config_file_path"]),
    )


def _unknown_policy_type_warning(policy_id: str, policy_type: str | None) -> str:
    return f"policy {policy_id}: skipped unknown policy type {policy_type}"


def _parse_fgac_row(
    row: DumpRow, names: Mapping[str, str]
) -> ParseResult[ParsedFgacPolicy]:
    parent = full_name(row, row["on_securable_type"])
    policy_id = f"{parent}#{row['policy_name']}"
    policy_kind = _FGAC_TYPES.get(row["policy_type"])
    if policy_kind is None:
        return None, (_unknown_policy_type_warning(policy_id, row["policy_type"]),)
    try:
        condition = parse_tag_condition(row["when_condition"])
        entries = tuple(parse_match_column(e) for e in row["match_columns"] or ())
    except ConditionParseError as error:
        return None, (_unparseable_warning(policy_id, error),)
    is_mask = policy_kind == "mask"
    aliases = _alias_first(entries, row["on_column"]) if is_mask else entries
    policy = _fgac_policy(row, names, parent, condition, aliases)
    parsed = ParsedFgacPolicy(
        policy=policy, condition=condition, alias_conditions=aliases
    )
    warnings = _unsupported_warnings(policy_id, condition) + tuple(
        w
        for alias, alias_condition in aliases
        for w in _unsupported_warnings(f"{policy_id} alias {alias}", alias_condition)
    )
    return parsed, warnings


def parse_fgac_policies(
    rows: Sequence[DumpRow], names: Mapping[str, str]
) -> tuple[tuple[ParsedFgacPolicy, ...], tuple[str, ...]]:
    """The mask and filter policies in ``abac_policies`` rows, and the warnings raised."""
    return _split_results([_parse_fgac_row(row, names) for row in rows])
