"""Deprecation warnings for config values that still work but are slated for removal.

The engine keeps honouring a deprecated value, so a config that uses one still loads
and deploys unchanged; these helpers only describe each use so the caller can warn the
author to migrate.
"""

from __future__ import annotations

from collections.abc import Iterator

from uc_abac.configs.models import (
    FunctionConfig,
    ResourcesConfig,
    RlsMappingRuleConfig,
)
from uc_abac.configs.rules import RLS_DEPRECATED_IDENTITIES
from uc_abac.configs.traversal import iter_securable_configs


def _filter_rule_functions(config: ResourcesConfig) -> Iterator[FunctionConfig]:
    """Yield every function in ``config`` whose body is defined by filter rules, in
    walk order. Functions with a raw ``return`` body carry no rules and are skipped."""
    for securable in iter_securable_configs(config):
        if isinstance(securable, FunctionConfig) and securable.has_filter_rules:
            yield securable


def _function_rules(function: FunctionConfig) -> Iterator[RlsMappingRuleConfig]:
    """Yield the rls_mapping rules of ``function`` from both rule lists, in
    ``match_rules`` then ``match_any_of_rules`` order. Condition rules are skipped
    because they carry no identity."""
    for rule in [*(function.match_rules or []), *(function.match_any_of_rules or [])]:
        if isinstance(rule, RlsMappingRuleConfig):
            yield rule


def _deprecated_identities_used(function: FunctionConfig) -> list[str]:
    """Return the distinct deprecated identities used by ``function``'s rules, in
    first-use order, so several rules sharing one deprecated identity count once."""
    identities = [
        rule.identity
        for rule in _function_rules(function)
        if rule.identity in RLS_DEPRECATED_IDENTITIES
    ]
    return list(dict.fromkeys(identities))


def _location_suffix(function: FunctionConfig) -> str:
    """Return the `` (file_path)`` suffix naming the file the function was written in,
    or an empty string when the function has no file path (e.g. built in code)."""
    if function.file_path is None:
        return ""
    return f" ({function.file_path})"


def _identity_warning(function: FunctionConfig, identity: str) -> str:
    """Describe one deprecated ``identity`` used by ``function``, naming the replacement
    from ``RLS_DEPRECATED_IDENTITIES``."""
    replacement = RLS_DEPRECATED_IDENTITIES[identity]
    return (
        f"FUNCTION {function.full_name}{_location_suffix(function)}: identity "
        f"'{identity}' is deprecated and will be removed in a future release; use "
        f"'{replacement}' instead ({identity}() is a deprecated alias of "
        f"{replacement}())."
    )


def _function_warnings(function: FunctionConfig) -> list[str]:
    """Return one warning per deprecated identity used by ``function``."""
    return [
        _identity_warning(function, identity)
        for identity in _deprecated_identities_used(function)
    ]


def deprecated_identity_warnings(config: ResourcesConfig) -> list[str]:
    """Return one warning message per filter-rule function that uses a deprecated
    rls ``identity`` (see ``RLS_DEPRECATED_IDENTITIES``).

    A function using the same deprecated identity in several rules yields a single
    message; a function using two different deprecated identities yields one per
    identity. Messages follow config walk order.
    """
    return [
        warning
        for function in _filter_rule_functions(config)
        for warning in _function_warnings(function)
    ]
