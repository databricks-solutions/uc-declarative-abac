"""Parse the rendered tag conditions in the uc-abac dump tables.

``abac_policies`` and ``pseudo_policies`` carry a policy's tag predicate as the SQL
``WHEN`` condition Unity Catalog stores (``when_condition``) and its ``MATCH COLUMNS``
entries as ``'<condition> AS <alias>'`` strings (``match_columns``). The viewer needs
them as structured tag predicates, so this module parses them back.

The grammar is the boolean expression ``uc_abac`` renders (see
``uc_abac.policies.render_tag_when_condition``): ``AND`` / ``OR`` / ``NOT`` over
parenthesised groups and atoms, where an atom is ``has_tag('<key>')``,
``has_tag_value('<key>', '<value>')``, or ``TRUE``. String literals are single-quoted
with an embedded quote doubled (``'O''Brien'``); keywords and function names are
case-insensitive.

The parsed expression is flattened into the engine's predicate shape: every conjunct
that is a positive tag atom joins ``has_tags`` (all must hold), a parenthesised ``OR``
of positive tag atoms becomes ``has_any_of_tags`` (at least one must hold), and a
negated tag atom joins ``has_none_of_tags`` (none may hold). A tag atom's value is
``"*"`` for ``has_tag`` (presence of the key, any value). ``TRUE`` conjuncts are
dropped, so an empty or ``TRUE`` condition matches every securable.

Anything the viewer cannot evaluate against tags — context or identity attribute
atoms, a second ``OR`` group, nested ``OR`` inside ``NOT``, or any other function — is
kept verbatim in ``unsupported``. A condition with an unsupported part never matches,
so the viewer can only under-report access, never invent it; the caller surfaces a
warning.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import reduce

TagAtom = tuple[str, str]

WILDCARD = "*"

# Binary operators and their precedence. AND binds tighter than OR; NOT binds tighter
# than both, so its operand is parsed with a floor above AND (see _parse_expression).
_OPERATORS = {"OR": 1, "AND": 2}
_LOWEST = 1
_NOT_FLOOR = 3
_RESERVED = frozenset({"AND", "OR", "NOT", "AS"})
_PUNCTUATION = "(),"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ConditionParseError(ValueError):
    """A condition string is not a well-formed boolean expression."""


def _holds(tags: Mapping[str, str], atom: TagAtom) -> bool:
    """Whether ``tags`` carries the atom's key, with its value unless the value is the
    wildcard (presence-only)."""
    key, value = atom
    return key in tags and (value == WILDCARD or tags[key] == value)


@dataclass(frozen=True)
class TagCondition:
    """A tag predicate parsed from a rendered condition.

    Atom tuples are ``(tag_key, tag_value)`` sorted by key, with value ``"*"`` for a
    presence-only atom.
    """

    has_tags: tuple[TagAtom, ...] = ()
    has_any_of_tags: tuple[TagAtom, ...] = ()
    has_none_of_tags: tuple[TagAtom, ...] = ()
    unsupported: tuple[str, ...] = ()

    def matches(self, tags: Mapping[str, str]) -> bool:
        """Whether a securable carrying ``tags`` satisfies the condition."""
        if self.unsupported:
            return False
        return (
            all(_holds(tags, atom) for atom in self.has_tags)
            and (
                not self.has_any_of_tags
                or any(_holds(tags, atom) for atom in self.has_any_of_tags)
            )
            and not any(_holds(tags, atom) for atom in self.has_none_of_tags)
        )

    def witness(self, tags: Mapping[str, str]) -> tuple[TagAtom, ...]:
        """The ``(key, actual value)`` tags that satisfied the positive atoms, sorted."""
        held = {
            (key, tags[key])
            for key, value in self.has_tags + self.has_any_of_tags
            if _holds(tags, (key, value))
        }
        return tuple(sorted(held))


# ---------------------------------------------------------------------------
# Expression tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    """A lexical token. ``text`` is the decoded value for a string literal, the raw
    word for an identifier, and the punctuation itself otherwise. ``start``/``end``
    are offsets into the scanned text."""

    kind: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _Call:
    """A function call with string-literal arguments; ``name`` is lowercased."""

    name: str
    args: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class _TrueLiteral:
    source: str


@dataclass(frozen=True)
class _Not:
    operand: _Expr
    source: str


@dataclass(frozen=True)
class _Junction:
    """A binary ``AND`` or ``OR``; ``operator`` is the uppercase keyword."""

    operator: str
    operands: tuple[_Expr, ...]
    source: str


_Expr = _Call | _TrueLiteral | _Not | _Junction


# ---------------------------------------------------------------------------
# Flattening the expression tree into TagCondition
# ---------------------------------------------------------------------------


def _tag_atom(expr: _Expr) -> TagAtom | None:
    """The ``(key, value)`` of a positive ``has_tag`` / ``has_tag_value`` call, else None."""
    if not isinstance(expr, _Call):
        return None
    if expr.name == "has_tag" and len(expr.args) == 1:
        return (expr.args[0], WILDCARD)
    if expr.name == "has_tag_value" and len(expr.args) == 2:
        return (expr.args[0], expr.args[1])
    return None


def _negated_tag_atom(expr: _Expr) -> TagAtom | None:
    """The atom of ``NOT <tag atom>``, else None."""
    if isinstance(expr, _Not):
        return _tag_atom(expr.operand)
    return None


def _flatten(expr: _Expr, operator: str) -> tuple[_Expr, ...]:
    """The operands of a chain of ``operator`` junctions, with nested same-operator
    junctions (from parentheses or left-associative parsing) expanded."""
    if isinstance(expr, _Junction) and expr.operator == operator:
        return tuple(
            leaf for operand in expr.operands for leaf in _flatten(operand, operator)
        )
    return (expr,)


def _or_group_atoms(expr: _Expr) -> tuple[TagAtom, ...]:
    """The atoms of an ``OR`` whose every disjunct is a positive tag atom; ``()`` for
    anything else (including an ``OR`` with a non-tag disjunct)."""
    if not (isinstance(expr, _Junction) and expr.operator == "OR"):
        return ()
    disjuncts = _flatten(expr, "OR")
    atoms = tuple(atom for atom in map(_tag_atom, disjuncts) if atom is not None)
    return atoms if len(atoms) == len(disjuncts) else ()


def _insert_atom(atoms: tuple[TagAtom, ...], atom: TagAtom) -> tuple[TagAtom, ...]:
    """Return ``atoms`` with ``atom`` added, kept sorted."""
    return tuple(sorted((*atoms, atom)))


def _add_conjunct(condition: TagCondition, conjunct: _Expr) -> TagCondition:
    """Fold one top-level AND conjunct into ``condition``, returning a new value.

    Only one OR group is representable; a second one, or any part that is not a tag
    atom, is recorded verbatim as unsupported.
    """
    if isinstance(conjunct, _TrueLiteral):
        return condition
    if atom := _tag_atom(conjunct):
        return replace(condition, has_tags=_insert_atom(condition.has_tags, atom))
    if atom := _negated_tag_atom(conjunct):
        return replace(
            condition,
            has_none_of_tags=_insert_atom(condition.has_none_of_tags, atom),
        )
    atoms = _or_group_atoms(conjunct)
    if atoms and not condition.has_any_of_tags:
        return replace(condition, has_any_of_tags=tuple(sorted(atoms)))
    return replace(condition, unsupported=(*condition.unsupported, conjunct.source))


def _condition_from_expression(expr: _Expr) -> TagCondition:
    """Flatten a parsed expression: its top-level AND conjuncts folded in order."""
    return reduce(_add_conjunct, _flatten(expr, "AND"), TagCondition())


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def _scan_string(text: str, start: int) -> tuple[str, int]:
    """Decode the single-quoted literal beginning at ``start``; a doubled quote inside
    the literal is one embedded quote. Returns the value and the offset past the
    closing quote."""
    chunks: tuple[str, ...] = ()
    pos = start + 1
    while True:
        close = text.find("'", pos)
        if close == -1:
            raise ConditionParseError(f"unterminated string literal at offset {start}")
        chunks += (text[pos:close],)
        if not text.startswith("'", close + 1):
            return "".join(chunks), close + 1
        chunks += ("'",)
        pos = close + 2


def _scan_token(text: str, pos: int) -> _Token:
    """Scan the token starting at ``pos``, which must not be whitespace."""
    char = text[pos]
    if char == "'":
        value, end = _scan_string(text, pos)
        return _Token("string", value, pos, end)
    if char in _PUNCTUATION:
        return _Token(char, char, pos, pos + 1)
    match = _IDENTIFIER.match(text, pos)
    if match is None:
        raise ConditionParseError(f"unexpected character {char!r} at offset {pos}")
    return _Token("ident", match.group(), pos, match.end())


def _tokenize(text: str) -> tuple[_Token, ...]:
    """Split ``text`` into tokens, skipping whitespace."""
    tokens: tuple[_Token, ...] = ()
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        token = _scan_token(text, pos)
        tokens += (token,)
        pos = token.end
    return tokens


def _token_at(tokens: tuple[_Token, ...], pos: int) -> _Token | None:
    return tokens[pos] if pos < len(tokens) else None


def _is_kind(tokens: tuple[_Token, ...], pos: int, kind: str) -> bool:
    token = _token_at(tokens, pos)
    return token is not None and token.kind == kind


def _is_keyword(tokens: tuple[_Token, ...], pos: int, word: str) -> bool:
    """Whether the token at ``pos`` is the identifier ``word``, ignoring case."""
    token = _token_at(tokens, pos)
    return token is not None and token.kind == "ident" and token.text.upper() == word


def _fail(tokens: tuple[_Token, ...], pos: int, expected: str) -> ConditionParseError:
    token = _token_at(tokens, pos)
    found = (
        "end of condition"
        if token is None
        else f"{token.text!r} at offset {token.start}"
    )
    return ConditionParseError(f"expected {expected}, found {found}")


def _expect(tokens: tuple[_Token, ...], pos: int, kind: str) -> int:
    """Consume a token of ``kind`` at ``pos``; returns the position after it."""
    if not _is_kind(tokens, pos, kind):
        raise _fail(tokens, pos, repr(kind))
    return pos + 1


def _span(src: str, tokens: tuple[_Token, ...], start: int, end: int) -> str:
    """The source text covering tokens ``[start, end)``."""
    return src[tokens[start].start : tokens[end - 1].end]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _binary_operator(tokens: tuple[_Token, ...], pos: int) -> str | None:
    """The ``AND`` / ``OR`` keyword at ``pos``, uppercased, or None."""
    token = _token_at(tokens, pos)
    if token is None or token.kind != "ident":
        return None
    word = token.text.upper()
    return word if word in _OPERATORS else None


def _expect_string(tokens: tuple[_Token, ...], pos: int) -> tuple[str, int]:
    token = _token_at(tokens, pos)
    if token is None or token.kind != "string":
        raise _fail(tokens, pos, "a string literal")
    return token.text, pos + 1


def _parse_arguments(
    tokens: tuple[_Token, ...], pos: int
) -> tuple[tuple[str, ...], int]:
    """Parse the arguments of a call; ``pos`` is just past the opening paren. Returns
    the decoded arguments and the position past the closing paren."""
    if _is_kind(tokens, pos, ")"):
        return (), pos + 1
    args: tuple[str, ...] = ()
    while True:
        value, pos = _expect_string(tokens, pos)
        args += (value,)
        if not _is_kind(tokens, pos, ","):
            return args, _expect(tokens, pos, ")")
        pos += 1


def _parse_atom(src: str, tokens: tuple[_Token, ...], pos: int) -> tuple[_Expr, int]:
    """Parse a leaf: a function call (any name) or ``TRUE``."""
    token = _token_at(tokens, pos)
    if token is None or token.kind != "ident" or token.text.upper() in _RESERVED:
        raise _fail(tokens, pos, "a function call or TRUE")
    if _is_kind(tokens, pos + 1, "("):
        args, end = _parse_arguments(tokens, pos + 2)
        return _Call(token.text.lower(), args, _span(src, tokens, pos, end)), end
    if token.text.upper() == "TRUE":
        return _TrueLiteral(_span(src, tokens, pos, pos + 1)), pos + 1
    raise _fail(tokens, pos, "'(' or TRUE")


def _parse_expression(
    src: str, tokens: tuple[_Token, ...], pos: int, floor: int
) -> tuple[_Expr, int]:
    """Parse an expression starting at ``pos``, consuming only binary operators whose
    precedence is at least ``floor`` (precedence climbing, left-associative).

    The prefix is ``NOT <operand>``, a parenthesised expression, or a leaf. The prefix
    and the operator loop share one function, so the grammar needs no mutually
    recursive helpers.
    """
    start = pos
    if _is_keyword(tokens, pos, "NOT"):
        operand, pos = _parse_expression(src, tokens, pos + 1, _NOT_FLOOR)
        left: _Expr = _Not(operand, _span(src, tokens, start, pos))
    elif _is_kind(tokens, pos, "("):
        left, pos = _parse_expression(src, tokens, pos + 1, _LOWEST)
        pos = _expect(tokens, pos, ")")
    else:
        left, pos = _parse_atom(src, tokens, pos)
    operator = _binary_operator(tokens, pos)
    while operator is not None and _OPERATORS[operator] >= floor:
        right, pos = _parse_expression(src, tokens, pos + 1, _OPERATORS[operator] + 1)
        left = _Junction(operator, (left, right), _span(src, tokens, start, pos))
        operator = _binary_operator(tokens, pos)
    return left, pos


def _split_alias(entry: str, tokens: tuple[_Token, ...]) -> tuple[str, str]:
    """Split a ``match_columns`` entry into ``(condition text, alias)``.

    The alias is the entry's final identifier, which must follow an ``AS`` keyword;
    the condition is everything before that ``AS``. For a well-formed entry this is the
    last top-level ``AS``: a string literal containing ``AS`` is a single token, and an
    ``AS`` inside parentheses is followed by a closing paren, not an identifier.
    """
    if (
        len(tokens) < 3
        or not _is_keyword(tokens, len(tokens) - 2, "AS")
        or tokens[-1].kind != "ident"
    ):
        raise ConditionParseError(f"match column {entry!r} must end with 'AS <alias>'")
    return entry[: tokens[-2].start], tokens[-1].text


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def parse_tag_condition(condition: str | None) -> TagCondition:
    """Parse a ``WHEN`` condition; ``None``, blank, or ``TRUE`` yields an empty
    (match-everything) condition. Raises ``ConditionParseError`` on malformed input."""
    if condition is None:
        return TagCondition()
    tokens = _tokenize(condition)
    if not tokens:
        return TagCondition()
    expr, pos = _parse_expression(condition, tokens, 0, _LOWEST)
    if pos != len(tokens):
        raise _fail(tokens, pos, "end of condition")
    return _condition_from_expression(expr)


def parse_match_column(entry: str) -> tuple[str, TagCondition]:
    """Parse one ``match_columns`` entry, ``'<condition> AS <alias>'``, into its alias
    and condition. The split is on the last top-level ``AS``. Raises
    ``ConditionParseError`` when the entry has no alias."""
    condition_text, alias = _split_alias(entry, _tokenize(entry))
    return alias, parse_tag_condition(condition_text)
