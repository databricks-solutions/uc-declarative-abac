from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from uc_abac.validator import load_config

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


def test_loader_resolves_bare_defs_rule_in_match_rules(tmp_yaml_dir):
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


def test_loader_resolves_ref_rule_with_parameter_override(tmp_yaml_dir):
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


def test_loader_substitutes_templated_rls_mapping_key(tmp_yaml_dir):
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


def test_loader_rejects_inline_mask_policy_function_using_match_rules(
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


def test_loader_rejects_override_repeating_a_rule_for_a_new_list(tmp_yaml_dir):
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
