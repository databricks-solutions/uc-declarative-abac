"""Shared vocabulary and pure helpers for row-filter rules (``match_rules`` /
``match_any_of_rules`` on a function config).

Lives in ``configs`` because both the config models (validation at load time) and the
securables compiler (rendering each ``rls_mapping`` key into a SQL literal) need the
same rules, and ``securables`` may import from ``configs`` but not the reverse.

An ``rls_mapping`` key is compared against a function parameter by the rule's
``operator``. The *comparison type* is the type a key must have: the parameter's own
type for infix operators and the string functions, the element type of an
``ARRAY<T>`` parameter for ``array_contains``, and the key type of a ``MAP<K, V>``
parameter for ``map_contains_key``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, get_args

from uc_abac.utils import sql_string_literal

RLS_WILDCARD = "*"

RlsInfixOperator = Literal[
    "=", "<", "<=", ">", ">=", "LIKE", "ILIKE", "RLIKE", "REGEXP"
]
RlsFunctionOperator = Literal[
    "array_contains",
    "map_contains_key",
    "regexp_like",
    "startswith",
    "endswith",
    "contains",
]
RlsOperator = Literal[RlsInfixOperator, RlsFunctionOperator]
RlsIdentity = Literal["is_account_group_member", "current_user"]

# bool before int (bool is an int subclass) and datetime before date (datetime is a
# date subclass) so the most specific YAML scalar type is reported in errors.
RlsKey = str | bool | int | float | datetime | date

RLS_INFIX_OPERATORS = frozenset(get_args(RlsInfixOperator))
RLS_FUNCTION_OPERATORS = frozenset(get_args(RlsFunctionOperator))


_STRING_TYPES = frozenset({"STRING", "VARCHAR", "CHAR"})
_INTEGRAL_TYPES = frozenset(
    {"TINYINT", "BYTE", "SMALLINT", "SHORT", "INT", "INTEGER", "BIGINT", "LONG"}
)
_FRACTIONAL_TYPES = frozenset({"FLOAT", "REAL", "DOUBLE", "DECIMAL", "DEC", "NUMERIC"})
_BOOLEAN_TYPES = frozenset({"BOOLEAN"})
_DATE_TYPES = frozenset({"DATE"})
_TIMESTAMP_TYPES = frozenset({"TIMESTAMP", "TIMESTAMP_NTZ"})

_TYPE_FAMILIES: dict[str, frozenset[str]] = {
    "string": _STRING_TYPES,
    "integral": _INTEGRAL_TYPES,
    "fractional": _FRACTIONAL_TYPES,
    "boolean": _BOOLEAN_TYPES,
    "date": _DATE_TYPES,
    "timestamp": _TIMESTAMP_TYPES,
}
_UNORDERABLE_FAMILIES = frozenset({"boolean"})
_STRING_OPERATORS = frozenset(
    {
        "LIKE",
        "ILIKE",
        "RLIKE",
        "REGEXP",
        "regexp_like",
        "startswith",
        "endswith",
        "contains",
    }
)
_ORDERING_OPERATORS = frozenset({"<", "<=", ">", ">="})

_TYPE_HEAD_PATTERN = re.compile(r"[A-Z_]+")


def _type_head(data_type: str) -> str:
    """Return the leading identifier of ``data_type`` (``DECIMAL(18,2)`` ->
    ``DECIMAL``, ``ARRAY<INT>`` -> ``ARRAY``, ``STRING COLLATE X`` -> ``STRING``)."""
    match = _TYPE_HEAD_PATTERN.match(data_type.strip().upper())
    return match.group(0) if match else ""


def _type_family(data_type: str) -> str | None:
    """Return the scalar family of ``data_type``, or ``None`` when it has no YAML
    scalar equivalent (complex, binary, interval, variant, ...)."""
    head = _type_head(data_type)
    return next(
        (family for family, heads in _TYPE_FAMILIES.items() if head in heads), None
    )


def _type_args(data_type: str) -> str:
    """Return the text between the outermost ``<`` and ``>`` of a complex type."""
    return data_type[data_type.index("<") + 1 : data_type.rindex(">")]


def _split_top_level(text: str) -> list[str]:
    """Split ``text`` on commas that aren't nested inside ``<>`` or ``()``, so
    ``STRING,MAP<INT,STRING>`` and ``DECIMAL(10,2),INT`` split into two parts."""
    parts: list[str] = []
    depth = 0
    current = ""
    for char in text:
        depth += {"<": 1, "(": 1, ">": -1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    return [*parts, current.strip()]


def _require_scalar(data_type: str, context: str) -> str:
    """Return ``data_type`` when it has a YAML scalar equivalent, else raise."""
    if _type_family(data_type) is None:
        raise ValueError(
            f"{context} has type {data_type}, which can't be expressed as an "
            "rls_mapping key; use a 'condition' rule instead"
        )
    return data_type


def _require_complex(operator: str, parameter_type: str, head: str) -> None:
    """Raise unless ``parameter_type`` is a ``head`` (``ARRAY`` / ``MAP``) type."""
    if _type_head(parameter_type) != head or "<" not in parameter_type:
        raise ValueError(
            f"operator '{operator}' requires a {head} parameter, got {parameter_type}"
        )


def _array_element_type(operator: str, parameter_type: str) -> str:
    _require_complex(operator, parameter_type, "ARRAY")
    element_type = _type_args(parameter_type).strip()
    return _require_scalar(element_type, f"the element of {parameter_type}")


def _map_key_type(operator: str, parameter_type: str) -> str:
    _require_complex(operator, parameter_type, "MAP")
    key_type = _split_top_level(_type_args(parameter_type))[0]
    return _require_scalar(key_type, f"the key of {parameter_type}")


def _scalar_operand_type(operator: str, parameter_type: str) -> str:
    """Comparison type for infix operators and the string functions: the parameter's
    own type, provided the operator is applicable to its family."""
    family = _type_family(_require_scalar(parameter_type, "the parameter"))
    if operator in _STRING_OPERATORS and family != "string":
        raise ValueError(
            f"operator '{operator}' requires a string parameter, got {parameter_type}"
        )
    if operator in _ORDERING_OPERATORS and family in _UNORDERABLE_FAMILIES:
        raise ValueError(
            f"operator '{operator}' can't be applied to a {parameter_type} parameter"
        )
    return parameter_type


_COMPLEX_OPERAND_TYPES: dict[str, Callable[[str, str], str]] = {
    "array_contains": _array_element_type,
    "map_contains_key": _map_key_type,
}


def _mismatch(key: object, comparison_type: str, hint: str = "") -> ValueError:
    suffix = f"; {hint}" if hint else ""
    return ValueError(
        f"rls_mapping key {key!r} is not a valid {comparison_type} value{suffix}"
    )


def _render_string(key: object, comparison_type: str) -> str:
    if not isinstance(key, str):
        raise _mismatch(key, comparison_type, "quote the key to use it as a string")
    return sql_string_literal(key)


def _render_integral(key: object, comparison_type: str) -> str:
    if isinstance(key, bool) or not isinstance(key, int | str):
        raise _mismatch(key, comparison_type)
    try:
        return str(int(key))
    except ValueError:
        raise _mismatch(key, comparison_type) from None


def _parse_decimal(key: object) -> Decimal | None:
    """Parse ``key`` as a finite ``Decimal`` (floats via ``str`` so ``0.1`` stays
    ``0.1``), or ``None`` when it isn't numeric."""
    if isinstance(key, bool) or not isinstance(key, int | float | str):
        return None
    try:
        value = Decimal(str(key))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _render_fractional(key: object, comparison_type: str) -> str:
    value = _parse_decimal(key)
    if value is None:
        raise _mismatch(key, comparison_type)
    return format(value.normalize(), "f")


def _render_boolean(key: object, comparison_type: str) -> str:
    if isinstance(key, bool):
        return "TRUE" if key else "FALSE"
    if isinstance(key, str) and key.lower() in {"true", "false"}:
        return key.upper()
    raise _mismatch(key, comparison_type)


def _parse_date(key: object) -> date | None:
    """A native ``datetime`` is deliberately not a valid ``DATE`` (it would silently
    drop its time component)."""
    if isinstance(key, datetime):
        return None
    if isinstance(key, date):
        return key
    try:
        return date.fromisoformat(key) if isinstance(key, str) else None
    except ValueError:
        return None


def _render_date(key: object, comparison_type: str) -> str:
    value = _parse_date(key)
    if value is None:
        raise _mismatch(key, comparison_type)
    return f"DATE'{value.isoformat()}'"


def _parse_datetime(key: object) -> datetime | None:
    """A native ``date`` that isn't a ``datetime`` is not a valid timestamp."""
    if isinstance(key, datetime):
        return key
    try:
        return datetime.fromisoformat(key) if isinstance(key, str) else None
    except ValueError:
        return None


def _render_timestamp(key: object, comparison_type: str) -> str:
    """``TIMESTAMP_NTZ`` rejects timezone-aware values, which it can't represent."""
    value = _parse_datetime(key)
    head = _type_head(comparison_type)
    if value is None or (head == "TIMESTAMP_NTZ" and value.tzinfo is not None):
        raise _mismatch(key, comparison_type)
    return f"{head}'{value.isoformat(sep=' ')}'"


_RENDERERS: dict[str, Callable[[object, str], str]] = {
    "string": _render_string,
    "integral": _render_integral,
    "fractional": _render_fractional,
    "boolean": _render_boolean,
    "date": _render_date,
    "timestamp": _render_timestamp,
}


def rls_comparison_type(operator: str, parameter_type: str) -> str:
    """Return the type an ``rls_mapping`` key must have for ``operator`` applied to a
    parameter of (normalised, upper-case) ``parameter_type``.

    Raises ``ValueError`` when the operator can't be applied to the parameter type
    (e.g. ``LIKE`` on an ``INT``, ``array_contains`` on a ``STRING``) or when the
    comparison type has no YAML scalar equivalent (binary, interval, struct, ...).
    """
    resolver = _COMPLEX_OPERAND_TYPES.get(operator, _scalar_operand_type)
    return resolver(operator, parameter_type)


def render_rls_key_literal(key: RlsKey, comparison_type: str) -> str:
    """Render ``key`` as a canonical Databricks SQL literal of ``comparison_type``.

    Native YAML scalars must match the comparison type exactly; a string key is also
    accepted for a non-string type when it parses as that type (so quoted and
    ``${placeholder}`` keys work). Canonical means equivalent keys render identically
    (``'042'`` and ``42`` both render ``42`` for an integral type), which lets callers
    detect duplicate keys. Raises ``ValueError`` on a mismatch.
    """
    family = _type_family(comparison_type)
    if family is None:
        raise ValueError(
            f"rls_mapping keys can't be compared as {comparison_type}; "
            "use a 'condition' rule instead"
        )
    return _RENDERERS[family](key, comparison_type)
