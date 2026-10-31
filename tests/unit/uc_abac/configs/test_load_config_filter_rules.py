from __future__ import annotations

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
                            "name": "user_in_region",
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
    assert [rule.name for rule in fn.match_rules] == ["user_in_region"]
    assert fn.match_rules[0].parameter == "region"


def test_load_config_resolves_ref_rule_with_parameter_and_name_override(
    tmp_yaml_dir,
):
    """A `$ref` to a rule definition may override its `name` and `parameter`."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "definitions": {
                    "rules": {
                        "region_rule": {
                            "name": "user_in_region",
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
                                "name": "user_in_home_region",
                                "parameter": "home_region",
                            },
                        ],
                    }
                ),
            },
        }
    )

    rule = _loaded_function(load_config(root)).match_rules[0]

    assert rule.name == "user_in_home_region"
    assert rule.parameter == "home_region"
    assert rule.rls_mapping == {"AMER": ["amer_readers"]}


def test_load_config_merges_override_rule_into_function_definition_by_name(
    tmp_yaml_dir,
):
    """A function `$ref` override adding a newly-named rule keeps the definition's rule."""
    root = tmp_yaml_dir(
        {
            "config.yaml": {
                "definitions": {
                    "functions": {
                        "region_filter": {
                            "name": "fn_filter",
                            "parameters": _REGION_PARAMS,
                            "match_rules": [
                                {
                                    "name": "user_in_region",
                                    "rls_mapping": {"AMER": "amer_readers"},
                                },
                            ],
                        },
                    },
                },
                "resources": _catalog_with_function(
                    {
                        "$ref": "$defs/functions/region_filter",
                        "match_rules": [
                            {
                                "name": "region_is_not_restricted",
                                "condition": "region <> 'RESTRICTED'",
                            },
                        ],
                    }
                ),
            },
        }
    )

    fn = _loaded_function(load_config(root))

    assert {rule.name for rule in fn.match_rules} == {
        "user_in_region",
        "region_is_not_restricted",
    }


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
                                    "name": "user_in_region",
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
                                                                "name": "r",
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
