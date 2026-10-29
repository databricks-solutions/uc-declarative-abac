"""Tests for parsing the rendered tag conditions stored by uc-abac dump.

The round-trip tests render with the real ``uc_abac`` renderer, so the parser is
checked against the exact output the dump tables contain.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from abac_viewer.backend.engine.conditions import (
    WILDCARD,
    ConditionParseError,
    TagCondition,
    parse_match_column,
    parse_tag_condition,
)
from uc_abac.policies import render_tag_when_condition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dict_semantics(
    has_tags: Mapping[str, str] | None,
    has_any_of_tags: Mapping[str, str] | None,
    tags: Mapping[str, str],
) -> bool:
    """Reference evaluation of a has_tags / has_any_of_tags pair over a tag map."""

    def present(key: str, value: str) -> bool:
        return key in tags and (value == WILDCARD or tags[key] == value)

    all_ok = all(present(k, v) for k, v in (has_tags or {}).items())
    any_ok = not has_any_of_tags or any(
        present(k, v) for k, v in has_any_of_tags.items()
    )
    return all_ok and any_ok


# ---------------------------------------------------------------------------
# TagCondition: empty / match-everything
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "condition",
    [None, "", "   ", "\n\t", "TRUE", "true", "True", "  tRuE  "],
    ids=["none", "empty", "spaces", "whitespace", "upper", "lower", "title", "padded"],
)
def test_conditions_empty_condition_matches_any_tags(condition: str | None) -> None:
    parsed = parse_tag_condition(condition)

    assert parsed.matches({})
    assert parsed.matches({"pii": "email", "region": "eu"})
    assert parsed.unsupported == ()


def test_tag_condition_is_frozen_dataclass() -> None:
    parsed = parse_tag_condition("has_tag('pii')")

    assert isinstance(parsed, TagCondition)
    with pytest.raises(AttributeError):
        parsed.has_tags = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TagCondition: single atoms
# ---------------------------------------------------------------------------


def test_tag_condition_has_tag_value_requires_exact_value() -> None:
    parsed = parse_tag_condition("has_tag_value('pii', 'email')")

    assert parsed.has_tags == (("pii", "email"),)
    assert parsed.matches({"pii": "email"})
    assert not parsed.matches({"pii": "phone"})
    assert not parsed.matches({"pii": "Email"})
    assert not parsed.matches({})


def test_tag_condition_has_tag_matches_key_presence_with_any_value() -> None:
    parsed = parse_tag_condition("has_tag('pii')")

    assert parsed.has_tags == (("pii", WILDCARD),)
    assert parsed.matches({"pii": "email"})
    assert parsed.matches({"pii": "phone"})
    assert not parsed.matches({"region": "eu"})
    assert not parsed.matches({})


# ---------------------------------------------------------------------------
# TagCondition: AND and OR groups
# ---------------------------------------------------------------------------


def test_tag_condition_multiple_and_atoms_all_must_hold() -> None:
    parsed = parse_tag_condition("has_tag_value('a', '1') AND has_tag_value('b', '2')")

    assert parsed.matches({"a": "1", "b": "2"})
    assert parsed.matches({"a": "1", "b": "2", "extra": "x"})
    assert not parsed.matches({"a": "1"})
    assert not parsed.matches({"b": "2"})
    assert not parsed.matches({"a": "1", "b": "3"})


def test_tag_condition_or_group_needs_at_least_one_atom() -> None:
    parsed = parse_tag_condition("(has_tag_value('a', '1') OR has_tag_value('a', '2'))")

    assert parsed.has_any_of_tags == (("a", "1"), ("a", "2"))
    assert parsed.has_tags == ()
    assert parsed.matches({"a": "1"})
    assert parsed.matches({"a": "2"})
    assert not parsed.matches({"a": "3"})
    assert not parsed.matches({})


def test_tag_condition_and_combined_with_or_group() -> None:
    parsed = parse_tag_condition(
        "has_tag_value('k', 'x') AND (has_tag_value('a', '1') OR has_tag_value('b', '2'))"
    )

    assert parsed.matches({"k": "x", "a": "1"})
    assert parsed.matches({"k": "x", "b": "2"})
    assert not parsed.matches({"a": "1"})
    assert not parsed.matches({"k": "x"})
    assert not parsed.matches({"k": "y", "a": "1"})


def test_tag_condition_or_group_with_presence_atom() -> None:
    parsed = parse_tag_condition("(has_tag('pii') OR has_tag_value('class', 'secret'))")

    assert parsed.matches({"pii": "anything"})
    assert parsed.matches({"class": "secret"})
    assert not parsed.matches({"class": "public"})


# ---------------------------------------------------------------------------
# TagCondition: NOT atoms
# ---------------------------------------------------------------------------


def test_tag_condition_not_value_atom_is_recorded_as_none_of() -> None:
    parsed = parse_tag_condition("has_tag('pii') AND NOT has_tag_value('region', 'eu')")

    assert parsed.has_tags == (("pii", WILDCARD),)
    assert parsed.has_none_of_tags == (("region", "eu"),)
    assert parsed.unsupported == ()


def test_tag_condition_not_value_atom_excludes_matching_tag() -> None:
    parsed = parse_tag_condition("has_tag('pii') AND NOT has_tag_value('region', 'eu')")

    assert parsed.matches({"pii": "email", "region": "us"})
    assert parsed.matches({"pii": "email"})
    assert not parsed.matches({"pii": "email", "region": "eu"})


@pytest.mark.parametrize(
    "excluded_tags",
    [{"secret": "yes"}, {"secret": "anything"}, {"secret": ""}],
    ids=["value", "other-value", "empty-value"],
)
def test_tag_condition_not_presence_atom_excludes_any_value(
    excluded_tags: dict[str, str],
) -> None:
    parsed = parse_tag_condition("NOT has_tag('secret')")

    assert parsed.has_none_of_tags == (("secret", WILDCARD),)
    assert not parsed.matches(excluded_tags)
    assert parsed.matches({})
    assert parsed.matches({"other": "x"})


def test_tag_condition_lowercase_not_is_negation() -> None:
    parsed = parse_tag_condition("has_tag('pii') and not has_tag('secret')")

    assert parsed.matches({"pii": "x"})
    assert not parsed.matches({"pii": "x", "secret": "y"})


# ---------------------------------------------------------------------------
# TagCondition: quoting and literal contents
# ---------------------------------------------------------------------------


def test_conditions_doubled_quote_is_single_quote_in_value() -> None:
    parsed = parse_tag_condition("has_tag_value('owner', 'O''Brien')")

    assert parsed.has_tags == (("owner", "O'Brien"),)
    assert parsed.matches({"owner": "O'Brien"})
    assert not parsed.matches({"owner": "OBrien"})
    assert not parsed.matches({"owner": "O''Brien"})


@pytest.mark.parametrize(
    ("value", "other"),
    [
        ("sales and marketing", "sales"),
        ("a AND b", "a"),
        ("x OR y", "x"),
        ("a, b, c", "a"),
        ("(draft)", "draft"),
        ("x) OR (y", "x"),
        ("rows: 5 (approx)", "rows: 5"),
    ],
    ids=["spaces", "AND", "OR", "comma", "parens", "paren-or", "colon-parens"],
)
def test_conditions_special_characters_inside_quotes_are_literal(
    value: str, other: str
) -> None:
    parsed = parse_tag_condition(f"has_tag_value('desc', '{value}')")

    assert parsed.unsupported == ()
    assert parsed.matches({"desc": value})
    assert not parsed.matches({"desc": other})


def test_conditions_keyword_inside_key_is_literal() -> None:
    parsed = parse_tag_condition("has_tag('a AND b')")

    assert parsed.unsupported == ()
    assert parsed.matches({"a AND b": "anything"})
    assert not parsed.matches({"a": "x", "b": "y"})


def test_conditions_keyword_inside_quotes_does_not_split_group() -> None:
    parsed = parse_tag_condition(
        "has_tag_value('k', 'x OR y') AND (has_tag_value('a', '1') OR has_tag_value('a', '2'))"
    )

    assert parsed.unsupported == ()
    assert parsed.matches({"k": "x OR y", "a": "2"})
    assert not parsed.matches({"k": "x", "a": "2"})


# ---------------------------------------------------------------------------
# TagCondition: keyword and function case-insensitivity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "condition",
    [
        "has_tag_value('a', '1') and has_tag_value('b', '2')",
        "HAS_TAG_VALUE('a', '1') AND HAS_TAG_VALUE('b', '2')",
        "Has_Tag_Value('a', '1') And Has_Tag_Value('b', '2')",
    ],
    ids=["lower-keyword", "upper", "mixed"],
)
def test_conditions_keywords_and_functions_are_case_insensitive(condition: str) -> None:
    parsed = parse_tag_condition(condition)

    assert parsed.unsupported == ()
    assert parsed.matches({"a": "1", "b": "2"})
    assert not parsed.matches({"a": "1"})


def test_conditions_or_group_keyword_is_case_insensitive() -> None:
    parsed = parse_tag_condition("(Has_Tag_Value('a', '1') or Has_Tag_Value('a', '2'))")

    assert parsed.unsupported == ()
    assert parsed.matches({"a": "2"})
    assert not parsed.matches({"a": "3"})


# ---------------------------------------------------------------------------
# TagCondition: round trip with the uc_abac renderer
# ---------------------------------------------------------------------------

_ROUND_TRIP_PAIRS: list[tuple[dict[str, str] | None, dict[str, str] | None]] = [
    ({"pii": "email"}, None),
    (None, {"region": "eu", "tier": "gold"}),
    ({"pii": WILDCARD}, {"region": "eu", "region2": "us"}),
    ({"a": "1", "b": "2"}, {"c": "3", "d": WILDCARD}),
    ({"env": "prod", "tier": WILDCARD}, {"team": "a", "team2": "b"}),
    ({"note": "O'Brien"}, {"desc": "a AND b"}),
    ({"owner": "x) OR (y"}, None),
]

_ROUND_TRIP_TAG_MAPS: list[dict[str, str]] = [
    {},
    {"pii": "email"},
    {"pii": "phone"},
    {"pii": "email", "region": "eu"},
    {"region": "eu"},
    {"region": "us", "tier": "gold"},
    {"a": "1", "b": "2", "c": "3", "d": "anything"},
    {"a": "1", "b": "2", "c": "3"},
    {"a": "1", "b": "2"},
    {"env": "prod", "tier": "silver", "team": "b"},
    {"env": "prod", "tier": "silver", "team2": "b"},
    {"env": "prod", "tier": "gold", "team": "a"},
    {"note": "O'Brien"},
    {"desc": "a AND b", "pii": "email"},
    {"owner": "x) OR (y", "team": "a"},
]


@pytest.mark.parametrize(
    ("has_tags", "has_any_of_tags"),
    _ROUND_TRIP_PAIRS,
    ids=[
        "single-and",
        "or-only",
        "and-presence-and-or",
        "multi-and-and-or",
        "and-with-presence-and-or",
        "quoted-values",
        "quoted-owner",
    ],
)
def test_conditions_round_trip_agrees_with_dict_semantics(
    has_tags: dict[str, str] | None,
    has_any_of_tags: dict[str, str] | None,
) -> None:
    rendered = render_tag_when_condition(has_tags, has_any_of_tags)
    parsed = parse_tag_condition(rendered)

    assert parsed.unsupported == ()
    for tags in _ROUND_TRIP_TAG_MAPS:
        expected = _dict_semantics(has_tags, has_any_of_tags, tags)
        assert parsed.matches(tags) == expected, (rendered, tags)


def test_conditions_round_trip_of_tagless_policy_matches_everything() -> None:
    rendered = render_tag_when_condition(None, None)
    parsed = parse_tag_condition(rendered)

    assert parsed.matches({})
    assert parsed.matches({"pii": "email"})


# ---------------------------------------------------------------------------
# TagCondition: unsupported parts never match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "condition",
    [
        "has_tag_value('pii', 'email') AND has_context_attribute_value('k', 'v')",
        "has_tag_value('pii', 'email') AND has_context_attribute('k')",
        "has_tag_value('pii', 'email') AND has_identity_attribute_value('group', 'x')",
        "has_tag_value('pii', 'email') AND has_something_unknown('k')",
        (
            "has_tag_value('pii', 'email') AND "
            "(has_tag_value('a', '1') OR has_tag_value('a', '2')) AND "
            "(has_tag_value('b', '1') OR has_tag_value('b', '2'))"
        ),
        "has_tag_value('pii', 'email') AND NOT (has_tag_value('a', '1') OR has_tag_value('b', '1'))",
    ],
    ids=[
        "context-value",
        "context-presence",
        "identity-value",
        "unknown-function",
        "second-or-group",
        "not-or-group",
    ],
)
def test_tag_condition_unsupported_part_records_and_never_matches(
    condition: str,
) -> None:
    parsed = parse_tag_condition(condition)

    assert parsed.unsupported
    assert not parsed.matches({"pii": "email", "a": "1", "b": "1"})
    assert not parsed.matches({"pii": "email"})


def test_tag_condition_unsupported_not_or_group_never_matches_empty_tags() -> None:
    parsed = parse_tag_condition(
        "NOT (has_tag_value('a', '1') OR has_tag_value('b', '1'))"
    )

    assert parsed.unsupported
    assert not parsed.matches({})


def test_conditions_supported_condition_records_no_unsupported() -> None:
    parsed = parse_tag_condition(
        "has_tag_value('pii', 'email') AND NOT has_tag('secret')"
    )

    assert parsed.unsupported == ()


# ---------------------------------------------------------------------------
# TagCondition: witness
# ---------------------------------------------------------------------------


def test_tag_condition_witness_returns_actual_values_sorted() -> None:
    parsed = parse_tag_condition("has_tag_value('pii', 'email') AND has_tag('region')")

    witness = parsed.witness({"region": "eu", "pii": "email", "other": "x"})

    assert witness == (("pii", "email"), ("region", "eu"))


def test_tag_condition_witness_excludes_unrelated_tags() -> None:
    parsed = parse_tag_condition("has_tag('pii')")

    witness = parsed.witness({"pii": "email", "owner": "bob", "zz": "1"})

    assert witness == (("pii", "email"),)


def test_tag_condition_witness_for_presence_atom_is_actual_value() -> None:
    parsed = parse_tag_condition("has_tag('tier')")

    assert parsed.witness({"tier": "gold"}) == (("tier", "gold"),)


def test_tag_condition_witness_for_or_group_reports_satisfying_value() -> None:
    parsed = parse_tag_condition("(has_tag_value('a', '1') OR has_tag_value('a', '2'))")

    assert parsed.witness({"a": "2", "z": "9"}) == (("a", "2"),)


def test_tag_condition_witness_is_sorted_by_key() -> None:
    parsed = parse_tag_condition("has_tag('zeta') AND has_tag('alpha')")

    witness = parsed.witness({"zeta": "1", "alpha": "2"})

    assert [key for key, _ in witness] == ["alpha", "zeta"]


def test_tag_condition_witness_empty_for_empty_condition() -> None:
    parsed = parse_tag_condition(None)

    assert parsed.witness({"pii": "email"}) == ()
    assert parsed.witness({}) == ()


# ---------------------------------------------------------------------------
# parse_tag_condition: malformed input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "condition",
    [
        "has_tag('pii'",
        "has_tag('pii'))",
        "(has_tag('a')",
        "((has_tag('a') OR has_tag('b'))",
        "has_tag_value('a', 'unterminated)",
        "has_tag('pii') AND",
        "AND has_tag('pii')",
        "has_tag('pii') OR",
        "()",
        "has_tag('a') AND ()",
    ],
    ids=[
        "unclosed-call",
        "extra-close-paren",
        "unclosed-group",
        "unclosed-outer-group",
        "unterminated-quote",
        "dangling-and",
        "leading-and",
        "dangling-or",
        "empty-parens",
        "empty-group-after-and",
    ],
)
def test_conditions_malformed_condition_raises_parse_error(condition: str) -> None:
    with pytest.raises(ConditionParseError):
        parse_tag_condition(condition)


def test_conditions_parse_error_is_value_error() -> None:
    assert issubclass(ConditionParseError, ValueError)


# ---------------------------------------------------------------------------
# parse_match_column
# ---------------------------------------------------------------------------


def test_conditions_match_column_splits_alias_and_condition() -> None:
    alias, condition = parse_match_column("has_tag_value('pii', 'email') AS col")

    assert alias == "col"
    assert condition.matches({"pii": "email"})
    assert not condition.matches({})


def test_conditions_match_column_true_condition_matches_everything() -> None:
    alias, condition = parse_match_column("TRUE AS any_col")

    assert alias == "any_col"
    assert condition.matches({})
    assert condition.matches({"pii": "email"})


def test_conditions_match_column_splits_on_last_as_when_value_contains_as() -> None:
    alias, condition = parse_match_column(
        "has_tag_value('desc', 'x AS y') AS real_alias"
    )

    assert alias == "real_alias"
    assert condition.matches({"desc": "x AS y"})
    assert not condition.matches({"desc": "x"})


def test_conditions_match_column_keyword_as_is_case_insensitive() -> None:
    alias, condition = parse_match_column("has_tag('pii') as col")

    assert alias == "col"
    assert condition.matches({"pii": "x"})


def test_conditions_match_column_or_group_condition_round_trips() -> None:
    rendered = render_tag_when_condition({"pii": "email"}, {"a": "1", "b": WILDCARD})
    alias, condition = parse_match_column(f"{rendered} AS masked")

    assert alias == "masked"
    assert condition.unsupported == ()
    assert condition.matches({"pii": "email", "b": "anything"})
    assert not condition.matches({"pii": "email"})


@pytest.mark.parametrize(
    "entry",
    ["has_tag('pii')", "TRUE", "has_tag_value('pii', 'email')"],
    ids=["tag-only", "true-only", "value-only"],
)
def test_conditions_match_column_without_alias_raises_parse_error(entry: str) -> None:
    with pytest.raises(ConditionParseError):
        parse_match_column(entry)


def test_conditions_match_column_malformed_condition_raises_parse_error() -> None:
    with pytest.raises(ConditionParseError):
        parse_match_column("(has_tag('pii') AS col")
