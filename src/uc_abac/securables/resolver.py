"""Resolve the principals of filter-rule functions and render their SQL bodies.

``render_function_bodies`` is internal to the securables differ: it runs before the
desired and actual functions are compared, so a filter-rule function's
``definition`` holds its rendered body by the time it is diffed against UC's
``routine_definition``. ``render_filter_rules`` is the pure renderer it uses.

The rendered text is compared byte-for-byte with ``routine_definition`` to decide
whether a function needs replacing, so the output format is frozen: changing it
re-creates every filter-rule function on the next deploy. Every rule is labelled
with an inline ``-- <rule name>`` comment at the end of its first line (rule names are
validated to contain no line breaks); when a condition's last line holds its own
``--`` comment, its closing parenthesis goes on a new line so it isn't commented out.
"""

from __future__ import annotations

import dataclasses
from textwrap import indent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uc_abac.logger import ChangeLogger
    from uc_abac.principals import PrincipalResolver

from uc_abac.configs import RLS_FUNCTION_OPERATORS
from uc_abac.principals import (
    Principal,
    ensure_resolved,
    log_principal_resolution_failure,
)
from uc_abac.securables.state import (
    ConditionRule,
    FilterRule,
    FilterRules,
    Function,
    RlsMappingRule,
    Securable,
)
from uc_abac.types import PrincipalType
from uc_abac.utils import (
    ExecutionError,
    OrchestratorError,
    PrincipalValidationError,
    sql_string_literal,
)

_INDENT = "  "


def _render_identity_check(identity: str, principal: Principal) -> str:
    """Render one principal's identity check, e.g. ``is_account_group_member('g')``
    or ``current_user() = 'u'``. Raises ``OrchestratorError`` for an unresolved
    principal, whose identifier would otherwise be missing."""
    literal = sql_string_literal(ensure_resolved(principal).identifier)
    if identity == "current_user":
        return f"current_user() = {literal}"
    return f"{identity}({literal})"


def _render_identity_checks(identity: str, principals: tuple[Principal, ...]) -> str:
    """OR together the identity checks of ``principals``, parenthesised when there
    is more than one."""
    checks = [_render_identity_check(identity, p) for p in principals]
    if len(checks) == 1:
        return checks[0]
    return "(" + " OR ".join(checks) + ")"


def _render_predicate(rule: RlsMappingRule, literal: str) -> str:
    """Render the parameter comparison: ``<op>(<parameter>, <literal>)`` for function
    operators, ``<parameter> <OP> <literal>`` for infix operators."""
    if rule.operator in RLS_FUNCTION_OPERATORS:
        return f"{rule.operator}({rule.parameter}, {literal})"
    return f"{rule.parameter} {rule.operator} {literal}"


def _render_entry(
    rule: RlsMappingRule, literal: str | None, principals: tuple[Principal, ...]
) -> str:
    """Render one ``rls_mapping`` entry; a wildcard (``None``) entry renders the
    identity checks alone, without any parameter comparison."""
    identities = _render_identity_checks(rule.identity, principals)
    if literal is None:
        return identities
    return f"({_render_predicate(rule, literal)} AND {identities})"


def _label_first_line(rendered: str, name: str) -> str:
    """Append the inline ``-- <name>`` comment to the end of ``rendered``'s first
    line. Rule names are validated to contain no line breaks, so the comment cannot
    spill onto the following lines."""
    first, newline, rest = rendered.partition("\n")
    return f"{first} -- {name}{newline}{rest}"


def _render_rls_mapping_rule(rule: RlsMappingRule) -> str:
    """Render the entries one per indented line, OR-joined, inside parentheses,
    with the rule's name comment after the opening parenthesis."""
    entries = [_render_entry(rule, lit, principals) for lit, principals in rule.entries]
    body = f"\n{_INDENT}OR ".join(entries)
    return _label_first_line(f"(\n{_INDENT}{body}\n)", rule.name)


def _render_condition_rule(rule: ConditionRule) -> str:
    """Render the stripped condition in parentheses, labelled on its first line.

    When the condition's last line contains ``--`` (e.g. its own trailing comment),
    the closing parenthesis goes on its own line, otherwise it would be commented
    out.
    """
    condition = rule.condition.strip()
    if "--" in condition.rsplit("\n", 1)[-1]:
        wrapped = f"({condition}\n)"
    else:
        wrapped = f"({condition})"
    return _label_first_line(wrapped, rule.name)


def _render_rule(rule: FilterRule) -> str:
    """Render a single rule, labelled with its name comment."""
    if isinstance(rule, ConditionRule):
        return _render_condition_rule(rule)
    return _render_rls_mapping_rule(rule)


def _render_group(rules: tuple[FilterRule, ...], joiner: str) -> str:
    """Join the rendered ``rules`` with a newline and ``joiner`` (``AND`` / ``OR``)."""
    return f"\n{joiner} ".join(_render_rule(rule) for rule in rules)


def _wrap_group(rules: tuple[FilterRule, ...], joiner: str) -> str:
    """Render a group for combination with the other group: a single rule is used
    as-is, several rules are wrapped in parentheses with every line indented."""
    rendered = _render_group(rules, joiner)
    if len(rules) == 1:
        return rendered
    return f"(\n{indent(rendered, _INDENT)}\n)"


def render_filter_rules(rules: FilterRules) -> str:
    """Render ``rules`` (whose principals must already be resolved) as a SQL boolean
    expression: ``all_of`` rules AND-joined, ``any_of`` rules OR-joined, and the two
    groups combined with AND.

    When only one group is present it is rendered unwrapped; when both are, each is
    wrapped (if it holds several rules) and the two are AND-joined. Raises
    ``OrchestratorError`` if any principal is unresolved.
    """
    if not rules.any_of:
        return _render_group(rules.all_of, "AND")
    if not rules.all_of:
        return _render_group(rules.any_of, "OR")
    return f"{_wrap_group(rules.all_of, 'AND')}\nAND {_wrap_group(rules.any_of, 'OR')}"


# Principal types each rls identity function can check membership / identity of.
_IDENTITY_PRINCIPAL_TYPES = {
    "is_account_group_member": frozenset({PrincipalType.GROUP}),
    "current_user": frozenset({PrincipalType.USER, PrincipalType.SERVICE_PRINCIPAL}),
}


class _UnrenderableFunctionError(Exception):
    """Raised internally when a filter-rule function can't be rendered; the failure
    has already been logged, so the caller only drops the function."""


def _resolve_rule_principal(
    principal: Principal,
    identity: str,
    full_name: str,
    resolver: PrincipalResolver,
    change_logger: ChangeLogger,
    ignore_unresolvable: frozenset[str],
) -> Principal:
    """Resolve one rule principal and check its type suits ``identity``.

    A resolution failure is logged via ``log_principal_resolution_failure`` (fatal,
    since rule principals come from config); a type mismatch (e.g. a user under
    ``is_account_group_member``) is logged as an ``ExecutionError``. Either way
    ``_UnrenderableFunctionError`` is raised so the whole function is dropped.
    """
    try:
        resolved = resolver.resolve_principal(principal)
    except PrincipalValidationError as exc:
        log_principal_resolution_failure(
            change_logger,
            f"Resolve principal for FUNCTION {full_name}",
            principal,
            exc,
            ignore_unresolvable,
        )
        raise _UnrenderableFunctionError from exc
    if resolved.principal_type not in _IDENTITY_PRINCIPAL_TYPES[identity]:
        change_logger.log_error(
            ExecutionError(
                context=f"Validate principal for FUNCTION {full_name}",
                exception=OrchestratorError(
                    f"Principal {principal.name!r} resolved to a "
                    f"{resolved.principal_type.value}, which identity '{identity}' "
                    "can't check."
                ),
            )
        )
        raise _UnrenderableFunctionError
    return resolved


def _resolve_rule(
    rule: FilterRule,
    full_name: str,
    resolver: PrincipalResolver,
    change_logger: ChangeLogger,
    ignore_unresolvable: frozenset[str],
) -> FilterRule:
    """Return ``rule`` with every rls_mapping principal resolved; condition rules
    reference no principals and pass through unchanged."""
    if isinstance(rule, ConditionRule):
        return rule
    entries = tuple(
        (
            literal,
            tuple(
                _resolve_rule_principal(
                    p,
                    rule.identity,
                    full_name,
                    resolver,
                    change_logger,
                    ignore_unresolvable,
                )
                for p in principals
            ),
        )
        for literal, principals in rule.entries
    )
    return dataclasses.replace(rule, entries=entries)


def _resolve_filter_rules(
    rules: FilterRules,
    full_name: str,
    resolver: PrincipalResolver,
    change_logger: ChangeLogger,
    ignore_unresolvable: frozenset[str],
) -> FilterRules:
    """Return ``rules`` with the principals of both rule groups resolved."""
    args = (full_name, resolver, change_logger, ignore_unresolvable)
    return FilterRules(
        all_of=tuple(_resolve_rule(r, *args) for r in rules.all_of),
        any_of=tuple(_resolve_rule(r, *args) for r in rules.any_of),
    )


def _render_function_body(
    securable: Securable,
    resolver: PrincipalResolver,
    change_logger: ChangeLogger,
    ignore_unresolvable: frozenset[str],
) -> Securable | None:
    """Return ``securable`` with its filter rules rendered into ``definition``, or
    ``None`` when a rule principal is unresolvable or unsuitable (already logged).
    Securables without filter rules are returned unchanged."""
    if not isinstance(securable, Function) or securable.filter_rules is None:
        return securable
    try:
        resolved = _resolve_filter_rules(
            securable.filter_rules,
            securable.full_name,
            resolver,
            change_logger,
            ignore_unresolvable,
        )
    except _UnrenderableFunctionError:
        return None
    return dataclasses.replace(
        securable, definition=render_filter_rules(resolved), filter_rules=None
    )


def render_function_bodies(
    desired: set[Securable],
    resolver: PrincipalResolver,
    change_logger: ChangeLogger,
    ignore_unresolvable: frozenset[str],
) -> set[Securable]:
    """Render the SQL body of every desired function defined by filter rules.

    Resolves each rule principal, checks it suits the rule's identity function, and
    renders the body into ``definition`` (clearing ``filter_rules``). A function with
    any unresolvable or unsuitable principal is logged as an error and dropped from
    the desired set, so a partial body is never deployed. Resolution stops at a
    function's first bad principal, so at most one error is logged per function.
    """
    rendered = (
        _render_function_body(s, resolver, change_logger, ignore_unresolvable)
        for s in desired
    )
    return {s for s in rendered if s is not None}
