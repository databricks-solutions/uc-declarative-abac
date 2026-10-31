from datetime import UTC, date, datetime

import pytest

from uc_abac.configs import render_rls_key_literal, rls_comparison_type

# ---------------------------------------------------------------------------
# rls_comparison_type
# ---------------------------------------------------------------------------

SCALAR_TYPES = [
    "STRING",
    "STRING COLLATE UTF8_LCASE",
    "VARCHAR(10)",
    "CHAR(3)",
    "TINYINT",
    "BYTE",
    "SMALLINT",
    "SHORT",
    "INT",
    "INTEGER",
    "BIGINT",
    "LONG",
    "FLOAT",
    "REAL",
    "DOUBLE",
    "DECIMAL",
    "DECIMAL(18,2)",
    "DEC(10,2)",
    "NUMERIC(5,0)",
    "BOOLEAN",
    "DATE",
    "TIMESTAMP",
    "TIMESTAMP_NTZ",
]

ORDERABLE_TYPES = [t for t in SCALAR_TYPES if t != "BOOLEAN"]

UNSUPPORTED_TYPES = [
    "BINARY",
    "INTERVAL DAY",
    "INTERVAL YEAR TO MONTH",
    "STRUCT<a:INT>",
    "VARIANT",
    "GEOGRAPHY",
]

STRING_OPERATORS = [
    "LIKE",
    "ILIKE",
    "RLIKE",
    "REGEXP",
    "regexp_like",
    "startswith",
    "endswith",
    "contains",
]

ORDERING_OPERATORS = ["<", "<=", ">", ">="]


@pytest.mark.parametrize("parameter_type", SCALAR_TYPES)
def test_rules_uses_parameter_type_as_comparison_type_for_equality(
    parameter_type,
):
    assert rls_comparison_type("=", parameter_type) == parameter_type


@pytest.mark.parametrize(
    "parameter_type", ["ARRAY<STRING>", "MAP<STRING,INT>", "STRUCT<a:INT>"]
)
def test_rules_rejects_equality_on_complex_parameter(parameter_type):
    with pytest.raises(ValueError):
        rls_comparison_type("=", parameter_type)


@pytest.mark.parametrize("parameter_type", UNSUPPORTED_TYPES)
def test_rules_rejects_equality_on_unsupported_parameter_suggesting_condition(
    parameter_type,
):
    with pytest.raises(ValueError, match="condition"):
        rls_comparison_type("=", parameter_type)


@pytest.mark.parametrize("operator", ORDERING_OPERATORS)
@pytest.mark.parametrize("parameter_type", ORDERABLE_TYPES)
def test_rules_uses_parameter_type_for_ordering_operator_on_orderable_parameter(
    operator, parameter_type
):
    assert rls_comparison_type(operator, parameter_type) == parameter_type


@pytest.mark.parametrize("operator", ORDERING_OPERATORS)
@pytest.mark.parametrize(
    "parameter_type", ["BOOLEAN", "ARRAY<INT>", "MAP<STRING,INT>", "BINARY"]
)
def test_rules_rejects_ordering_operator_on_unorderable_parameter(
    operator, parameter_type
):
    with pytest.raises(ValueError):
        rls_comparison_type(operator, parameter_type)


@pytest.mark.parametrize("operator", STRING_OPERATORS)
@pytest.mark.parametrize(
    "parameter_type",
    ["STRING", "STRING COLLATE UTF8_LCASE", "VARCHAR(10)", "CHAR(3)"],
)
def test_rules_uses_parameter_type_for_string_operator_on_string_parameter(
    operator, parameter_type
):
    assert rls_comparison_type(operator, parameter_type) == parameter_type


@pytest.mark.parametrize("operator", STRING_OPERATORS)
@pytest.mark.parametrize(
    "parameter_type",
    ["INT", "DECIMAL(18,2)", "BOOLEAN", "DATE", "TIMESTAMP", "ARRAY<STRING>"],
)
def test_rules_rejects_string_operator_on_non_string_parameter(
    operator, parameter_type
):
    with pytest.raises(ValueError):
        rls_comparison_type(operator, parameter_type)


def test_rules_rejects_like_on_integer_parameter():
    with pytest.raises(ValueError):
        rls_comparison_type("LIKE", "INT")


@pytest.mark.parametrize(
    ("parameter_type", "expected"),
    [
        ("ARRAY<STRING>", "STRING"),
        ("ARRAY<INT>", "INT"),
        ("ARRAY<DECIMAL(10,2)>", "DECIMAL(10,2)"),
        ("ARRAY<STRING COLLATE UTF8_LCASE>", "STRING COLLATE UTF8_LCASE"),
        ("ARRAY<DATE>", "DATE"),
    ],
)
def test_rules_uses_element_type_for_array_contains(parameter_type, expected):
    assert rls_comparison_type("array_contains", parameter_type) == expected


@pytest.mark.parametrize("parameter_type", ["STRING", "INT", "MAP<STRING,INT>"])
def test_rules_rejects_array_contains_on_non_array_parameter(parameter_type):
    with pytest.raises(ValueError):
        rls_comparison_type("array_contains", parameter_type)


@pytest.mark.parametrize(
    "parameter_type",
    ["ARRAY<BINARY>", "ARRAY<STRUCT<a:INT>>", "ARRAY<ARRAY<STRING>>"],
)
def test_rules_rejects_array_contains_when_element_type_is_unsupported(
    parameter_type,
):
    with pytest.raises(ValueError):
        rls_comparison_type("array_contains", parameter_type)


@pytest.mark.parametrize(
    ("parameter_type", "expected"),
    [
        ("MAP<STRING,INT>", "STRING"),
        ("MAP<INT,STRING>", "INT"),
        ("MAP<STRING,ARRAY<INT>>", "STRING"),
        ("MAP<STRING,MAP<INT,STRING>>", "STRING"),
        ("MAP<DECIMAL(10,2),INT>", "DECIMAL(10,2)"),
    ],
)
def test_rules_uses_key_type_for_map_contains_key(parameter_type, expected):
    assert rls_comparison_type("map_contains_key", parameter_type) == expected


@pytest.mark.parametrize("parameter_type", ["STRING", "INT", "ARRAY<STRING>"])
def test_rules_rejects_map_contains_key_on_non_map_parameter(parameter_type):
    with pytest.raises(ValueError):
        rls_comparison_type("map_contains_key", parameter_type)


def test_rules_rejects_map_contains_key_when_key_type_is_unsupported():
    with pytest.raises(ValueError):
        rls_comparison_type("map_contains_key", "MAP<BINARY,INT>")


# ---------------------------------------------------------------------------
# render_rls_key_literal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "comparison_type",
    ["STRING", "STRING COLLATE UTF8_LCASE", "VARCHAR(10)", "CHAR(4)"],
)
def test_rules_renders_string_key_as_quoted_literal(comparison_type):
    assert render_rls_key_literal("AMER", comparison_type) == "'AMER'"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("O'Brien", "'O\\'Brien'"),
        ('say "hi"', "'say \\\"hi\\\"'"),
        ("back\\slash", "'back\\\\slash'"),
    ],
)
def test_rules_escapes_special_characters_in_string_key(key, expected):
    assert render_rls_key_literal(key, "STRING") == expected


@pytest.mark.parametrize("key", [False, True, 42, 1.5, date(2026, 5, 2)])
def test_rules_rejects_native_non_string_key_for_string_type_suggesting_quote(
    key,
):
    with pytest.raises(ValueError, match="quote"):
        render_rls_key_literal(key, "STRING")


@pytest.mark.parametrize(
    ("key", "expected"),
    [(42, "42"), (-7, "-7"), (0, "0"), ("042", "42"), ("-7", "-7"), ("42", "42")],
)
@pytest.mark.parametrize("comparison_type", ["INT", "BIGINT", "TINYINT", "SMALLINT"])
def test_rules_renders_integral_key_as_canonical_integer(
    key, expected, comparison_type
):
    assert render_rls_key_literal(key, comparison_type) == expected


@pytest.mark.parametrize("key", [1.5, 2.0, "1.5", "abc", "", True, False])
def test_rules_rejects_non_integer_key_for_integral_type(key):
    with pytest.raises(ValueError):
        render_rls_key_literal(key, "INT")


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (1.5, "1.5"),
        ("1.50", "1.5"),
        ("1e3", "1000"),
        (100, "100"),
        (0.1, "0.1"),
        (2.0, "2"),
        ("-3.250", "-3.25"),
    ],
)
@pytest.mark.parametrize(
    "comparison_type", ["DECIMAL(18,2)", "DECIMAL", "DOUBLE", "FLOAT", "NUMERIC(5,2)"]
)
def test_rules_renders_fractional_key_as_canonical_plain_decimal(
    key, expected, comparison_type
):
    assert render_rls_key_literal(key, comparison_type) == expected


@pytest.mark.parametrize("key", ["abc", "", True, False])
def test_rules_rejects_non_numeric_key_for_fractional_type(key):
    with pytest.raises(ValueError):
        render_rls_key_literal(key, "DECIMAL(18,2)")


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (True, "TRUE"),
        (False, "FALSE"),
        ("true", "TRUE"),
        ("FALSE", "FALSE"),
        ("True", "TRUE"),
    ],
)
def test_rules_renders_boolean_key_as_keyword(key, expected):
    assert render_rls_key_literal(key, "BOOLEAN") == expected


@pytest.mark.parametrize("key", [1, 0, "yes", "1"])
def test_rules_rejects_non_boolean_key_for_boolean_type(key):
    with pytest.raises(ValueError):
        render_rls_key_literal(key, "BOOLEAN")


@pytest.mark.parametrize("key", [date(2026, 5, 2), "2026-05-02"])
def test_rules_renders_date_key_as_date_literal(key):
    assert render_rls_key_literal(key, "DATE") == "DATE'2026-05-02'"


@pytest.mark.parametrize(
    "key", [datetime(2026, 5, 2, 10, 0, 0), "not-a-date", "2026-13-01", 20260502]
)
def test_rules_rejects_invalid_key_for_date_type(key):
    with pytest.raises(ValueError):
        render_rls_key_literal(key, "DATE")


@pytest.mark.parametrize(
    "key",
    [datetime(2026, 5, 2, 10, 0, 0), "2026-05-02 10:00:00", "2026-05-02T10:00:00"],
)
@pytest.mark.parametrize(
    ("comparison_type", "prefix"),
    [("TIMESTAMP", "TIMESTAMP"), ("TIMESTAMP_NTZ", "TIMESTAMP_NTZ")],
)
def test_rules_renders_timestamp_key_as_timestamp_literal(key, comparison_type, prefix):
    assert (
        render_rls_key_literal(key, comparison_type) == f"{prefix}'2026-05-02 10:00:00'"
    )


@pytest.mark.parametrize("comparison_type", ["TIMESTAMP", "TIMESTAMP_NTZ"])
@pytest.mark.parametrize("key", [date(2026, 5, 2), "not-a-timestamp", 1714644000])
def test_rules_rejects_invalid_key_for_timestamp_type(key, comparison_type):
    with pytest.raises(ValueError):
        render_rls_key_literal(key, comparison_type)


@pytest.mark.parametrize(
    "key",
    [
        datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC),
        "2026-05-02T10:00:00+00:00",
    ],
)
def test_rules_rejects_timezone_aware_key_for_timestamp_ntz_type(key):
    with pytest.raises(ValueError):
        render_rls_key_literal(key, "TIMESTAMP_NTZ")


@pytest.mark.parametrize(
    "comparison_type", ["STRING", "INT", "DECIMAL(18,2)", "BOOLEAN", "DATE"]
)
def test_rules_rejects_none_key(comparison_type):
    with pytest.raises(ValueError):
        render_rls_key_literal(None, comparison_type)
