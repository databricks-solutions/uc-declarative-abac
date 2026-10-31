"""Tests for ``securables/resolver.py``: rendering filter rules into SQL and resolving
filter-rule functions' principals.

The rendered SQL text is compared byte-for-byte with UC's ``routine_definition`` to
decide whether a filter-rule function needs replacing, so the output format is a
frozen idempotency contract. Exact-string assertions on ``render_filter_rules`` are
therefore deliberate: any change to the rendered text is a behaviour change (it
re-creates every filter-rule function on the next deploy), not an implementation
detail. Every rule is labelled with an inline ``-- <rule name>`` SQL comment at the
end of its first line.

Principal resolution is internal to the securables differ, so it is exercised
through the public ``compute_securable_diff`` entry point.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from uc_abac.logger import ChangeLogger
from uc_abac.principals import (
    Principal,
    PrincipalResolver,
)
from uc_abac.securables import (
    ConditionRule,
    FilterRules,
    Function,
    RlsMappingRule,
    compute_securable_diff,
    render_filter_rules,
)
from uc_abac.types import (
    PrincipalType,
    SecurableType,
)
from uc_abac.utils import OrchestratorError


def _group(name: str) -> Principal:
    return Principal(principal_type=PrincipalType.GROUP, name=name, identifier=name)


def _user(username: str) -> Principal:
    return Principal(
        principal_type=PrincipalType.USER, name=username, identifier=username
    )


def _service_principal(display_name: str, application_id: str) -> Principal:
    return Principal(
        principal_type=PrincipalType.SERVICE_PRINCIPAL,
        name=display_name,
        identifier=application_id,
    )


def _rls(
    entries: tuple[tuple[str | None, tuple[Principal, ...]], ...],
    *,
    name: str = "rule",
    parameter: str | None = "region",
    operator: str = "=",
    identity: str = "is_account_group_member",
) -> RlsMappingRule:
    return RlsMappingRule(
        name=name,
        parameter=parameter,
        operator=operator,
        identity=identity,
        entries=entries,
    )


def _region_rule() -> RlsMappingRule:
    return _rls(
        (
            ("'AFRICA'", (_group("africa_readers"),)),
            ("'ASIA'", (_group("a"), _group("b"))),
            (None, (_group("global_readers"),)),
        ),
        name="region_access",
    )


_REGION_RULE_SQL = (
    "( -- region_access\n"
    "  (region = 'AFRICA' AND is_account_group_member('africa_readers'))\n"
    "  OR (region = 'ASIA' AND (is_account_group_member('a')"
    " OR is_account_group_member('b')))\n"
    "  OR is_account_group_member('global_readers')\n"
    ")"
)


# ---------------------------------------------------------------------------
# RlsMappingRule entries
# ---------------------------------------------------------------------------


def test_securable_resolver_single_rule_with_single_entry():
    """One rule with one literal entry and one principal renders a single
    predicate AND identity check inside the rule's parentheses."""
    rules = FilterRules(all_of=(_rls((("'AMER'", (_group("amer_readers"),)),)),))

    assert render_filter_rules(rules) == (
        "( -- rule\n  (region = 'AMER' AND is_account_group_member('amer_readers'))\n)"
    )


def test_securable_resolver_ors_identities_when_entry_has_several_principals():
    """An entry with several principals ORs their identity checks in parentheses."""
    rules = FilterRules(
        all_of=(_rls((("'AMER'", (_group("a"), _group("b"), _group("c"))),)),)
    )

    assert render_filter_rules(rules) == (
        "( -- rule\n"
        "  (region = 'AMER' AND (is_account_group_member('a')"
        " OR is_account_group_member('b') OR is_account_group_member('c')))\n"
        ")"
    )


def test_securable_resolver_wildcard_entry_renders_identity_alone():
    """A wildcard entry among literal entries renders only its identity check, and
    entries keep their declared order."""
    rules = FilterRules(all_of=(_region_rule(),))

    assert render_filter_rules(rules) == _REGION_RULE_SQL


def test_securable_resolver_labels_rls_mapping_rule_with_name_comment():
    """An rls_mapping rule carries its name as an inline comment after its
    opening parenthesis."""
    rules = FilterRules(
        all_of=(
            _rls(
                ((None, (_group("fraud_analysts"),)),),
                name="user_is_fraud_analyst",
                parameter=None,
            ),
        )
    )

    assert render_filter_rules(rules) == (
        "( -- user_is_fraud_analyst\n  is_account_group_member('fraud_analysts')\n)"
    )


def test_securable_resolver_wildcard_only_rule_ignores_parameter_and_operator():
    """A rule whose only entry is a wildcard renders just the identity check, with
    no parameter or operator."""
    rules = FilterRules(
        all_of=(
            _rls(
                ((None, (_group("fraud_analysts"),)),),
                parameter=None,
                operator="array_contains",
            ),
        )
    )

    assert render_filter_rules(rules) == (
        "( -- rule\n  is_account_group_member('fraud_analysts')\n)"
    )


def test_securable_resolver_wildcard_only_rule_with_several_principals():
    """A wildcard-only entry with several principals ORs them in parentheses."""
    rules = FilterRules(
        all_of=(_rls(((None, (_group("x"), _group("y"))),), parameter=None),)
    )

    assert render_filter_rules(rules) == (
        "( -- rule\n  (is_account_group_member('x') OR is_account_group_member('y'))\n)"
    )


# ---------------------------------------------------------------------------
# Operators and literals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "literal", "expected_predicate"),
    [
        ("=", "'AMER'", "region = 'AMER'"),
        ("<=", "42", "region <= 42"),
        ("LIKE", "'AM%'", "region LIKE 'AM%'"),
    ],
)
def test_securable_resolver_infix_operator_renders_parameter_operator_literal(
    operator: str, literal: str, expected_predicate: str
):
    """Infix operators render as ``<parameter> <OP> <literal>``."""
    rules = FilterRules(all_of=(_rls(((literal, (_group("g"),)),), operator=operator),))

    assert render_filter_rules(rules) == (
        f"( -- rule\n  ({expected_predicate} AND is_account_group_member('g'))\n)"
    )


@pytest.mark.parametrize("operator", ["array_contains", "map_contains_key"])
def test_securable_resolver_function_operator_renders_function_call(operator: str):
    """Function operators render as ``<op>(<parameter>, <literal>)``."""
    rules = FilterRules(
        all_of=(
            _rls((("'AMER'", (_group("g"),)),), parameter="regions", operator=operator),
        )
    )

    assert render_filter_rules(rules) == (
        f"( -- rule\n  ({operator}(regions, 'AMER') AND is_account_group_member('g'))\n)"
    )


def test_securable_resolver_passes_typed_literals_through_unchanged():
    """Entry keys are already-rendered SQL literals and appear verbatim."""
    rules = FilterRules(
        all_of=(
            _rls((("42", (_group("g"),)),), name="tenant", parameter="tenant_id"),
            _rls(
                (("DATE'2026-05-02'", (_group("h"),)),),
                name="as_of",
                parameter="as_of",
                operator=">=",
            ),
        )
    )

    assert render_filter_rules(rules) == (
        "( -- tenant\n  (tenant_id = 42 AND is_account_group_member('g'))\n)\n"
        "AND ( -- as_of\n  (as_of >= DATE'2026-05-02' AND is_account_group_member('h'))\n)"
    )


# ---------------------------------------------------------------------------
# Identity functions
# ---------------------------------------------------------------------------


def test_securable_resolver_escapes_quotes_in_group_name():
    """A quote in a principal identifier is backslash-escaped in the SQL literal."""
    rules = FilterRules(all_of=(_rls(((None, (_group("o'brien"),)),), parameter=None),))

    assert render_filter_rules(rules) == (
        "( -- rule\n  is_account_group_member('o\\'brien')\n)"
    )


def test_securable_resolver_current_user_compares_username_for_user():
    """``current_user`` identity compares against a user's username."""
    rules = FilterRules(
        all_of=(
            _rls(
                (("'AMER'", (_user("a@x.com"),)),),
                identity="current_user",
            ),
        )
    )

    assert render_filter_rules(rules) == (
        "( -- rule\n  (region = 'AMER' AND current_user() = 'a@x.com')\n)"
    )


def test_securable_resolver_current_user_compares_application_id_for_service_principal():
    """``current_user`` identity compares against a service principal's application
    id, not its display name."""
    app_id = "11111111-2222-3333-4444-555555555555"
    rules = FilterRules(
        all_of=(
            _rls(
                ((None, (_service_principal("My SP", app_id),)),),
                parameter=None,
                identity="current_user",
            ),
        )
    )

    assert render_filter_rules(rules) == f"( -- rule\n  current_user() = '{app_id}'\n)"


# ---------------------------------------------------------------------------
# ConditionRule
# ---------------------------------------------------------------------------


def test_securable_resolver_condition_rule_is_wrapped_and_stripped():
    """A condition rule renders its stripped condition in parentheses."""
    rules = FilterRules(all_of=(ConditionRule("small", "  amount < 10000\n"),))

    assert render_filter_rules(rules) == "(amount < 10000) -- small"


def test_securable_resolver_labels_condition_rule_with_name_comment():
    """A condition rule is followed by an inline comment carrying its name."""
    rules = FilterRules(all_of=(ConditionRule("amount_is_small", "amount < 10000"),))

    assert render_filter_rules(rules) == "(amount < 10000) -- amount_is_small"


def test_securable_resolver_labels_multiline_condition_on_first_line():
    """A multi-line condition carries its name comment on its first line, so the
    closing parenthesis on the last line stays live SQL."""
    rules = FilterRules(all_of=(ConditionRule("name", "a\nAND b"),))

    assert render_filter_rules(rules) == "(a -- name\nAND b)"


def test_securable_resolver_moves_closing_paren_to_own_line_when_condition_ends_in_comment():
    """When the condition's last line ends in its own ``--`` comment, the closing
    parenthesis goes on its own line so it is not commented out."""
    rules = FilterRules(
        all_of=(ConditionRule("small", "amount < 10000 -- small only"),)
    )

    assert render_filter_rules(rules) == "(amount < 10000 -- small only -- small\n)"


# ---------------------------------------------------------------------------
# Rule groups
# ---------------------------------------------------------------------------


def test_securable_resolver_all_of_rules_are_and_joined():
    """``all_of`` rules are joined with a newline and AND."""
    rules = FilterRules(
        all_of=(
            ConditionRule("small", "amount < 10000"),
            ConditionRule("recent", "year >= 2020"),
            ConditionRule("active", "is_active"),
        )
    )

    assert render_filter_rules(rules) == (
        "(amount < 10000) -- small\nAND (year >= 2020) -- recent\nAND (is_active) -- active"
    )


def test_securable_resolver_any_of_rules_are_or_joined():
    """``any_of`` rules are joined with a newline and OR."""
    rules = FilterRules(
        any_of=(
            ConditionRule("small", "amount < 10000"),
            _rls(((None, (_group("fraud_analysts"),)),), parameter=None),
        )
    )

    assert render_filter_rules(rules) == (
        "(amount < 10000) -- small\n"
        "OR ( -- rule\n  is_account_group_member('fraud_analysts')\n)"
    )


def test_securable_resolver_combined_groups_wraps_and_indents_multi_rule_group():
    """With both groups present, a single-rule group is used as-is and a
    multi-rule group is wrapped in parentheses with every line indented."""
    rules = FilterRules(
        all_of=(_region_rule(),),
        any_of=(
            ConditionRule("small", "amount < 10000"),
            _rls(((None, (_group("fraud_analysts"),)),), parameter=None),
        ),
    )

    assert render_filter_rules(rules) == (
        _REGION_RULE_SQL + "\n"
        "AND (\n"
        "  (amount < 10000) -- small\n"
        "  OR ( -- rule\n"
        "    is_account_group_member('fraud_analysts')\n"
        "  )\n"
        ")"
    )


def test_securable_resolver_combined_groups_wraps_both_when_both_multi_rule():
    """With both groups holding several rules, each group is wrapped and indented."""
    rules = FilterRules(
        all_of=(
            ConditionRule("small", "amount < 10000"),
            ConditionRule("recent", "year >= 2020"),
        ),
        any_of=(
            ConditionRule("emea", "region = 'EMEA'"),
            ConditionRule("apac", "region = 'APAC'"),
        ),
    )

    assert render_filter_rules(rules) == (
        "(\n"
        "  (amount < 10000) -- small\n"
        "  AND (year >= 2020) -- recent\n"
        ")\n"
        "AND (\n"
        "  (region = 'EMEA') -- emea\n"
        "  OR (region = 'APAC') -- apac\n"
        ")"
    )


def test_securable_resolver_combined_groups_uses_single_rule_groups_as_is():
    """With both groups holding a single rule, neither is wrapped."""
    rules = FilterRules(
        all_of=(ConditionRule("small", "amount < 10000"),),
        any_of=(ConditionRule("emea", "region = 'EMEA'"),),
    )

    assert render_filter_rules(rules) == (
        "(amount < 10000) -- small\nAND (region = 'EMEA') -- emea"
    )


# ---------------------------------------------------------------------------
# Determinism and validation
# ---------------------------------------------------------------------------


def test_securable_resolver_is_deterministic():
    """Rendering the same rules twice yields identical, non-empty text."""
    rules = FilterRules(
        all_of=(_region_rule(),),
        any_of=(ConditionRule("small", "amount < 10000"),),
    )

    first = render_filter_rules(rules)

    assert first
    assert render_filter_rules(rules) == first


def test_securable_resolver_raises_when_principal_unresolved():
    """An unresolved principal cannot be rendered and raises OrchestratorError."""
    unresolved = Principal(principal_type=PrincipalType.UNKNOWN, name="ghost")
    rules = FilterRules(all_of=(_rls((("'AMER'", (unresolved,)),)),))

    with pytest.raises(OrchestratorError):
        render_filter_rules(rules)


def _change_logger() -> ChangeLogger:
    return ChangeLogger()


def _make_function(
    full_name: str = "catalog.schema.my_func",
    parameters: tuple[tuple[str, str], ...] = (("x", "STRING"),),
    definition: str = "RETURN x",
) -> Function:
    """Helper to build a Function with sensible defaults."""
    return Function(
        securable_type=SecurableType.FUNCTION,
        full_name=full_name,
        parameters=parameters,
        definition=definition,
    )


# ---------------------------------------------------------------------------
# Filter-rule function body rendering
# ---------------------------------------------------------------------------

_FILTER_FUNC_NAME = "catalog.schema.region_filter"
_SP_APPLICATION_ID = "6f1c1d2e-0000-4000-8000-000000000001"


def _resolved_principals() -> dict[str, Principal]:
    """Display name -> resolved Principal known to the filter-rule test resolver."""
    return {
        "amer_readers": Principal(
            PrincipalType.GROUP, name="amer_readers", identifier="amer_readers"
        ),
        "emea_readers": Principal(
            PrincipalType.GROUP, name="emea_readers", identifier="emea_readers"
        ),
        "global_readers": Principal(
            PrincipalType.GROUP, name="global_readers", identifier="global_readers"
        ),
        "jdoe@example.com": Principal(
            PrincipalType.USER, name="jdoe@example.com", identifier="jdoe@example.com"
        ),
        "etl-bot": Principal(
            PrincipalType.SERVICE_PRINCIPAL,
            name="etl-bot",
            identifier=_SP_APPLICATION_ID,
        ),
    }


def _filter_rule_resolver() -> PrincipalResolver:
    """A resolver whose ws_helper resolves the names in ``_resolved_principals`` and
    raises PrincipalValidationError for any other name."""
    from uc_abac.utils import PrincipalValidationError

    known = _resolved_principals()

    def resolve_by_name(name: str) -> Principal:
        if name not in known:
            raise PrincipalValidationError(f"Principal not found by name: {name}")
        return known[name]

    ws_helper = MagicMock()
    ws_helper.resolve_by_name.side_effect = resolve_by_name
    return PrincipalResolver(ws_helper)


def _unresolved(name: str) -> Principal:
    return Principal(PrincipalType.UNKNOWN, name=name)


def _resolved(name: str) -> Principal:
    return _resolved_principals()[name]


def _region_rules(
    principal: Callable[[str], Principal],
    *,
    amer: str = "amer_readers",
    identity: str = "is_account_group_member",
) -> FilterRules:
    """A region rls rule plus an admin condition, with principals built by
    ``principal`` (unresolved for desired state, resolved for expected output)."""
    return FilterRules(
        all_of=(
            RlsMappingRule(
                name="region_access",
                parameter="region",
                operator="=",
                identity=identity,
                entries=(
                    ("'AMER'", (principal(amer),)),
                    ("'EMEA'", (principal("emea_readers"),)),
                    (None, (principal("global_readers"),)),
                ),
            ),
        ),
        any_of=(
            ConditionRule(name="admins", condition="is_account_group_member('admins')"),
        ),
    )


def _filter_function(rules: FilterRules) -> Function:
    """A desired Function whose body is defined by ``rules``."""
    return Function(
        securable_type=SecurableType.FUNCTION,
        full_name=_FILTER_FUNC_NAME,
        parameters=(("region", "STRING"),),
        definition="",
        filter_rules=rules,
    )


def _single_rule_function(identity: str, principal_name: str) -> Function:
    """A desired Function with one wildcard rls rule for ``principal_name``."""
    return _filter_function(
        FilterRules(
            all_of=(
                RlsMappingRule(
                    name="rule",
                    parameter=None,
                    operator="=",
                    identity=identity,
                    entries=((None, (_unresolved(principal_name),)),),
                ),
            )
        )
    )


def _actual_function(definition: str) -> Function:
    """The actual-state Function as fetched from UC, carrying ``definition``."""
    return _make_function(
        full_name=_FILTER_FUNC_NAME,
        parameters=(("region", "STRING"),),
        definition=definition,
    )


def test_securable_resolver_renders_filter_rule_function_body():
    """A desired filter-rule function absent from UC is created with its rules'
    principals resolved and rendered into definition, and filter_rules cleared."""
    desired = _filter_function(_region_rules(_unresolved))

    diff = compute_securable_diff(
        set(), set(), {desired}, set(), _filter_rule_resolver(), _change_logger()
    )

    assert len(diff.securables_to_create) == 1
    (created,) = diff.securables_to_create
    assert isinstance(created, Function)
    assert created.full_name == _FILTER_FUNC_NAME
    assert created.filter_rules is None
    assert "is_account_group_member('amer_readers')" in created.definition
    assert created.definition == render_filter_rules(_region_rules(_resolved))
    assert diff.securables_to_replace == []


def test_securable_resolver_detects_no_change_when_rendered_body_matches_actual():
    """A filter-rule function whose rendered body equals UC's definition is neither
    created nor replaced."""
    desired = _filter_function(_region_rules(_unresolved))
    actual = _actual_function(render_filter_rules(_region_rules(_resolved)))
    change_logger = _change_logger()

    diff = compute_securable_diff(
        set(), set(), {desired}, {actual}, _filter_rule_resolver(), change_logger
    )

    assert diff.securables_to_create == []
    assert diff.securables_to_replace == []
    assert change_logger.has_errors is False


def test_securable_resolver_replaces_function_when_rendered_body_differs():
    """A changed mapping renders a different body from UC's definition, so the
    function is replaced with the newly rendered body."""
    desired = _filter_function(_region_rules(_unresolved, amer="global_readers"))
    actual = _actual_function(render_filter_rules(_region_rules(_resolved)))

    diff = compute_securable_diff(
        set(), set(), {desired}, {actual}, _filter_rule_resolver(), _change_logger()
    )

    assert diff.securables_to_create == []
    assert len(diff.securables_to_replace) == 1
    (replaced,) = diff.securables_to_replace
    assert isinstance(replaced, Function)
    assert replaced.definition == render_filter_rules(
        _region_rules(_resolved, amer="global_readers")
    )
    assert diff.old_securables[_FILTER_FUNC_NAME] == actual


def test_securable_resolver_logs_error_and_drops_function_when_principal_unknown():
    """A filter-rule principal that can't be resolved logs an error and drops the
    function, so a partial body is never deployed."""
    desired = _filter_function(_region_rules(_unresolved, amer="no_such_group"))
    actual = _actual_function(render_filter_rules(_region_rules(_resolved)))
    change_logger = _change_logger()

    diff = compute_securable_diff(
        set(), set(), {desired}, {actual}, _filter_rule_resolver(), change_logger
    )

    assert change_logger.has_errors is True
    assert diff.securables_to_create == []
    assert diff.securables_to_replace == []


def test_securable_resolver_logs_error_and_drops_new_function_when_principal_unknown():
    """An unresolvable principal on a filter-rule function not yet in UC logs an
    error and the function is not created."""
    desired = _filter_function(_region_rules(_unresolved, amer="no_such_group"))
    change_logger = _change_logger()

    diff = compute_securable_diff(
        set(), set(), {desired}, set(), _filter_rule_resolver(), change_logger
    )

    assert change_logger.has_errors is True
    assert diff.securables_to_create == []
    assert diff.securables_to_replace == []


def test_securable_resolver_logs_error_when_group_identity_resolves_to_user():
    """is_account_group_member with a principal that resolves to a user is an
    error, and the function is dropped."""
    desired = _single_rule_function("is_account_group_member", "jdoe@example.com")
    change_logger = _change_logger()

    diff = compute_securable_diff(
        set(), set(), {desired}, set(), _filter_rule_resolver(), change_logger
    )

    assert change_logger.has_errors is True
    assert diff.securables_to_create == []
    assert diff.securables_to_replace == []


def test_securable_resolver_logs_error_when_current_user_identity_resolves_to_group():
    """current_user with a principal that resolves to a group is an error, and the
    function is dropped."""
    desired = _single_rule_function("current_user", "amer_readers")
    change_logger = _change_logger()

    diff = compute_securable_diff(
        set(), set(), {desired}, set(), _filter_rule_resolver(), change_logger
    )

    assert change_logger.has_errors is True
    assert diff.securables_to_create == []
    assert diff.securables_to_replace == []


def test_securable_resolver_renders_current_user_identity_for_user():
    """current_user with a principal that resolves to a user renders that user's
    name without error."""
    desired = _single_rule_function("current_user", "jdoe@example.com")
    change_logger = _change_logger()

    diff = compute_securable_diff(
        set(), set(), {desired}, set(), _filter_rule_resolver(), change_logger
    )

    assert change_logger.has_errors is False
    (created,) = diff.securables_to_create
    assert isinstance(created, Function)
    assert "current_user() = 'jdoe@example.com'" in created.definition


def test_securable_resolver_renders_application_id_for_service_principal_current_user():
    """current_user with a service principal renders its application id, not its
    display name."""
    desired = _single_rule_function("current_user", "etl-bot")
    change_logger = _change_logger()

    diff = compute_securable_diff(
        set(), set(), {desired}, set(), _filter_rule_resolver(), change_logger
    )

    assert change_logger.has_errors is False
    (created,) = diff.securables_to_create
    assert isinstance(created, Function)
    assert f"current_user() = '{_SP_APPLICATION_ID}'" in created.definition
    assert "etl-bot" not in created.definition


def test_securable_resolver_diffs_return_function_without_filter_rules_as_before():
    """A desired function defined by ``return`` (no filter_rules) keeps its
    definition untouched: created as-is when absent, unchanged when it matches."""
    desired = _actual_function("region = 'AMER'")

    created_diff = compute_securable_diff(
        set(), set(), {desired}, set(), _filter_rule_resolver(), _change_logger()
    )
    unchanged_diff = compute_securable_diff(
        set(), set(), {desired}, {desired}, _filter_rule_resolver(), _change_logger()
    )

    assert created_diff.securables_to_create == [desired]
    (created,) = created_diff.securables_to_create
    assert isinstance(created, Function)
    assert created.definition == "region = 'AMER'"
    assert unchanged_diff.securables_to_create == []
    assert unchanged_diff.securables_to_replace == []
