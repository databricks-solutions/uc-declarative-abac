from __future__ import annotations

import logging
import re

import pytest
from pydantic import ValidationError

from uc_abac.orchestrator import load_config

# ---------------------------------------------------------------------------
# Function filter rules through the full offline load_config pipeline
# (discovery -> resolve_refs -> consolidate_resources -> ResourcesConfig)
# ---------------------------------------------------------------------------

_REGION_PARAMS = [{"name": "region", "type": "string"}]


def _catalog_with_function(function: dict) -> dict:
    """A resources block with one catalog/schema holding ``function``."""
    return {
        "catalogs": {
            "cat": {
                "name": "cat",
                "schemas": [{"name": "sch", "functions": [function]}],
            },
        },
    }


def _loaded_function(config):
    """Return the single function loaded into ``cat.sch``."""
    return config.catalogs["cat"].schemas[0].functions[0]


def test_load_config_resolves_bare_defs_rule_in_match_rules(tmp_yaml_dir):
    """A rule under `definitions: rules:` may be referenced as a bare `$defs/...` item."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "definitions": {
                    "rules": {
                        "region_rule": {
                            "rls_mapping": {"AMER": "amer_readers"},
                        },
                    },
                },
                "resources": _catalog_with_function(
                    {
                        "name": "fn_filter",
                        "parameters": _REGION_PARAMS,
                        "match_rules": ["$defs/rules/region_rule"],
                    }
                ),
            },
        }
    )

    fn = _loaded_function(load_config(root))

    assert fn.has_filter_rules is True
    assert len(fn.match_rules) == 1
    assert fn.match_rules[0].rls_mapping == {"AMER": ["amer_readers"]}
    assert fn.match_rules[0].parameter == "region"


def test_load_config_resolves_ref_rule_with_parameter_override(tmp_yaml_dir):
    """A `$ref` to a rule definition may override its `parameter`."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "definitions": {
                    "rules": {
                        "region_rule": {
                            "rls_mapping": {"AMER": "amer_readers"},
                        },
                    },
                },
                "resources": _catalog_with_function(
                    {
                        "name": "fn_filter",
                        "parameters": [
                            {"name": "region", "type": "string"},
                            {"name": "home_region", "type": "string"},
                        ],
                        "match_rules": [
                            {
                                "$ref": "$defs/rules/region_rule",
                                "parameter": "home_region",
                            },
                        ],
                    }
                ),
            },
        }
    )

    rule = _loaded_function(load_config(root)).match_rules[0]

    assert rule.parameter == "home_region"
    assert rule.rls_mapping == {"AMER": ["amer_readers"]}


def test_load_config_substitutes_templated_rls_mapping_key(tmp_yaml_dir):
    """An `rls_mapping` key may be a `${placeholder}` bound by the `$ref`'s `$vars`."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "definitions": {
                    "functions": {
                        "region_filter": {
                            "$vars": {"region": None},
                            "name": "fn_filter",
                            "parameters": _REGION_PARAMS,
                            "match_rules": [
                                {
                                    "rls_mapping": {"${region}": "regional_readers"},
                                },
                            ],
                        },
                    },
                },
                "resources": _catalog_with_function(
                    {
                        "$ref": "$defs/functions/region_filter",
                        "$vars": {"region": "EMEA"},
                    }
                ),
            },
        }
    )

    rule = _loaded_function(load_config(root)).match_rules[0]

    assert rule.rls_mapping == {"EMEA": ["regional_readers"]}


def test_load_config_rejects_inline_mask_policy_function_using_match_rules(
    tmp_yaml_dir,
):
    """An inline mask-policy function defined by filter rules fails to load."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "resources": {
                    "catalogs": {
                        "cat": {
                            "name": "cat",
                            "schemas": [
                                {
                                    "name": "sch",
                                    "tables": [
                                        {
                                            "name": "t",
                                            "policies": [
                                                {
                                                    "name": "m",
                                                    "type": "mask",
                                                    "function": {
                                                        "name": "fn_filter",
                                                        "parameters": _REGION_PARAMS,
                                                        "match_rules": [
                                                            {
                                                                "rls_mapping": {
                                                                    "AMER": "g"
                                                                },
                                                            },
                                                        ],
                                                    },
                                                    "columns": [
                                                        {
                                                            "alias": "region",
                                                            "has_tags": {
                                                                "pii": "region"
                                                            },
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                },
            },
        }
    )

    with pytest.raises(ValidationError, match="mask"):
        load_config(root)


def test_load_config_rejects_override_repeating_a_rule_for_a_new_list(tmp_yaml_dir):
    """A `$ref` override that adds a list repeating the same rule fails to load."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "definitions": {
                    "rules": {
                        "region_rule": {
                            "rls_mapping": {"AMER": "amer_readers"},
                        },
                    },
                    "functions": {
                        "region_filter": {
                            "name": "fn_filter",
                            "parameters": _REGION_PARAMS,
                            "match_rules": [{"condition": "region = 'EMEA'"}],
                        },
                    },
                },
                "resources": _catalog_with_function(
                    {
                        "$ref": "$defs/functions/region_filter",
                        "match_any_of_rules": [
                            {"$ref": "$defs/rules/region_rule"},
                            {"$ref": "$defs/rules/region_rule"},
                        ],
                    }
                ),
            },
        }
    )

    with pytest.raises(ValidationError, match=re.escape("match_any_of_rules[1]")):
        load_config(root)


# ---------------------------------------------------------------------------
# Deprecated `identity: current_user` on RLS mapping rules
# ---------------------------------------------------------------------------


def _deprecation_warnings(caplog, function_full_name: str) -> list[str]:
    """Warning messages that mention the function and the deprecated identity."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
        and function_full_name in r.getMessage()
        and "current_user" in r.getMessage()
    ]


def test_load_config_warns_when_function_uses_deprecated_current_user_identity(
    tmp_yaml_dir, caplog
):
    """A function whose RLS rule uses the deprecated `current_user` identity logs a
    warning naming the function and recommending `session_user`, but still loads."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "resources": _catalog_with_function(
                    {
                        "name": "fn_filter",
                        "parameters": _REGION_PARAMS,
                        "match_rules": [
                            {
                                "rls_mapping": {"AMER": "someone@example.com"},
                                "identity": "current_user",
                            },
                        ],
                    }
                ),
            },
        }
    )

    with caplog.at_level(logging.WARNING, logger="uc_abac"):
        config = load_config(root)

    fn = _loaded_function(config)
    assert fn.match_rules[0].identity == "current_user"
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "cat.sch.fn_filter" in m and "current_user" in m and "session_user" in m
        for m in messages
    ), f"no deprecation warning naming cat.sch.fn_filter in {messages}"


def test_load_config_does_not_warn_for_session_user_identity(tmp_yaml_dir, caplog):
    """A function whose RLS rule uses the `session_user` identity logs no deprecation
    warning."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "resources": _catalog_with_function(
                    {
                        "name": "fn_filter",
                        "parameters": _REGION_PARAMS,
                        "match_rules": [
                            {
                                "rls_mapping": {"AMER": "someone@example.com"},
                                "identity": "session_user",
                            },
                        ],
                    }
                ),
            },
        }
    )

    with caplog.at_level(logging.WARNING, logger="uc_abac"):
        load_config(root)

    assert not any(
        r.levelno == logging.WARNING
        and ("current_user" in r.getMessage() or "deprecated" in r.getMessage().lower())
        for r in caplog.records
    )


def test_load_config_warns_once_per_function_using_current_user(tmp_yaml_dir, caplog):
    """A function using `current_user` in several rules (across match_rules and
    match_any_of_rules) logs exactly one deprecation warning for that function."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "resources": _catalog_with_function(
                    {
                        "name": "fn_filter",
                        "parameters": _REGION_PARAMS,
                        "match_rules": [
                            {
                                "rls_mapping": {"AMER": "someone@example.com"},
                                "identity": "current_user",
                            },
                        ],
                        "match_any_of_rules": [
                            {
                                "rls_mapping": {"EMEA": "other@example.com"},
                                "identity": "current_user",
                            },
                        ],
                    }
                ),
            },
        }
    )

    with caplog.at_level(logging.WARNING, logger="uc_abac"):
        load_config(root)

    assert len(_deprecation_warnings(caplog, "cat.sch.fn_filter")) == 1
