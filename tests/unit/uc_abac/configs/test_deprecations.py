from __future__ import annotations

from uc_abac.configs import ResourcesConfig, deprecated_identity_warnings
from uc_abac.orchestrator import load_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REGION_PARAMS = [{"name": "region", "type": "string"}]


def _rls_rule(identity: str | None = None, key: str = "AMER") -> dict:
    """An rls_mapping rule, optionally carrying an explicit identity."""
    rule = {"rls_mapping": {key: f"{key.lower()}_readers"}}
    if identity is not None:
        rule["identity"] = identity
    return rule


def _function(name: str = "fn", **body) -> dict:
    """A function dict in ``cat.sch`` with the region parameter and the given body fields."""
    return {"name": name, "parameters": _REGION_PARAMS, **body}


def _resources(*functions: dict) -> dict:
    """A resources block with ``cat.sch`` holding ``functions``."""
    return {
        "catalogs": {
            "cat": {
                "name": "cat",
                "schemas": [{"name": "sch", "functions": list(functions)}],
            },
        },
    }


def _config(*functions: dict) -> ResourcesConfig:
    return ResourcesConfig.model_validate(_resources(*functions))


# ---------------------------------------------------------------------------
# deprecated_identity_warnings
# ---------------------------------------------------------------------------


def test_deprecations_returns_no_warnings_when_no_function_uses_current_user():
    """Functions using session_user, session_user_or_member or the default identity
    produce no deprecation warnings."""
    config = _config(
        _function(
            "fn_session",
            match_rules=[_rls_rule("session_user")],
        ),
        _function(
            "fn_session_or_member",
            match_any_of_rules=[_rls_rule("session_user_or_member", key="EMEA")],
        ),
        _function(
            "fn_default",
            match_rules=[_rls_rule(key="APAC")],
        ),
    )

    assert deprecated_identity_warnings(config) == []


def test_deprecations_returns_no_warnings_for_function_with_return_body():
    """A function defined by a raw `return` expression has no rules, so it is ignored."""
    config = _config(_function("fn_return", **{"return": "'x'"}))

    assert deprecated_identity_warnings(config) == []


def test_deprecations_returns_warning_when_current_user_in_match_rules():
    """A function using current_user in match_rules yields one warning."""
    config = _config(
        _function("fn", match_rules=[_rls_rule("current_user")]),
    )

    warnings = deprecated_identity_warnings(config)

    assert len(warnings) == 1


def test_deprecations_returns_warning_when_current_user_in_match_any_of_rules():
    """A function using current_user in match_any_of_rules yields one warning."""
    config = _config(
        _function("fn", match_any_of_rules=[_rls_rule("current_user")]),
    )

    warnings = deprecated_identity_warnings(config)

    assert len(warnings) == 1


def test_deprecations_returns_single_warning_when_current_user_in_several_rules():
    """Several current_user rules across both rule lists in one function still yield
    one warning for that function."""
    config = _config(
        _function(
            "fn",
            match_rules=[_rls_rule("current_user", key="AMER")],
            match_any_of_rules=[
                _rls_rule("current_user", key="EMEA"),
                _rls_rule("current_user", key="APAC"),
            ],
        ),
    )

    warnings = deprecated_identity_warnings(config)

    assert len(warnings) == 1


def test_deprecations_returns_one_warning_per_affected_function_in_walk_order():
    """Each function using current_user gets its own warning, in config walk order."""
    config = _config(
        _function("fn_a", match_rules=[_rls_rule("current_user")]),
        _function("fn_clean", match_rules=[_rls_rule("session_user", key="EMEA")]),
        _function("fn_b", match_any_of_rules=[_rls_rule("current_user", key="APAC")]),
    )

    warnings = deprecated_identity_warnings(config)

    assert len(warnings) == 2
    assert "cat.sch.fn_a" in warnings[0]
    assert "cat.sch.fn_b" in warnings[1]


def test_deprecations_warning_names_function_identity_and_replacement():
    """The warning names the function's full name, the deprecated identity and the
    recommended replacement."""
    config = _config(
        _function("fn", match_rules=[_rls_rule("current_user")]),
    )

    warnings = deprecated_identity_warnings(config)

    assert len(warnings) == 1
    message = warnings[0]
    assert "cat.sch.fn" in message
    assert "current_user" in message
    assert "session_user" in message


def test_deprecations_warning_names_config_file_the_function_was_written_in(
    tmp_yaml_dir,
):
    """A config loaded from disk yields a warning naming the file the function is in."""
    root = tmp_yaml_dir(
        {
            "resources/fn_filter.yaml": {
                "resources": _resources(
                    _function("fn", match_rules=[_rls_rule("current_user")]),
                ),
            },
        }
    )

    warnings = deprecated_identity_warnings(load_config(root))

    assert len(warnings) == 1
    assert "fn_filter.yaml" in warnings[0]
