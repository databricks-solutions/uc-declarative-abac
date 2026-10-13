from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from uc_declarative_abac.cli.settings import resolve_settings
from uc_declarative_abac.utils import DuplicateKeyError


@pytest.mark.parametrize(
    ("file_value", "env_value", "cli_value", "expected"),
    [
        pytest.param(None, None, None, "system", id="default"),
        pytest.param("from-file", None, None, "from-file", id="settings-file"),
        pytest.param(
            "from-file", "from-env", None, "from-env", id="environment-over-file"
        ),
        pytest.param(
            "from-file", "from-env", "from-cli", "from-cli", id="cli-over-environment"
        ),
    ],
)
def test_given_system_catalog_sources_when_settings_are_resolved_then_normal_precedence_applies(
    file_value: str | None,
    env_value: str | None,
    cli_value: str | None,
    expected: str,
    monkeypatch,
    tmp_path: Path,
):
    # Given
    monkeypatch.chdir(tmp_path)
    if file_value is not None:
        (tmp_path / "uc_abac.yml").write_text(
            yaml.dump({"system_catalog": file_value}), encoding="utf-8"
        )
    if env_value is not None:
        monkeypatch.setenv("UC_ABAC_SYSTEM_CATALOG", env_value)
    cli_overrides = {"system_catalog": cli_value} if cli_value is not None else {}

    # When
    settings = resolve_settings(cli_overrides, settings_file=None)

    # Then
    assert settings.system_catalog == expected


def test_settings_prefers_cli_flag_over_env_var(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("UC_ABAC_WAREHOUSE_ID", "from-env")
    settings = resolve_settings(
        {"warehouse_id": "from-cli"},
        settings_file=None,
    )
    assert settings.warehouse_id == "from-cli"


def test_settings_prefers_env_var_over_settings_file(tmp_path: Path, monkeypatch):
    settings_path = tmp_path / "uc_abac.yml"
    settings_path.write_text(yaml.dump({"warehouse_id": "from-file"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UC_ABAC_WAREHOUSE_ID", "from-env")
    settings = resolve_settings({}, settings_file=None)
    assert settings.warehouse_id == "from-env"


def test_settings_rejects_unknown_key_in_settings_file(tmp_path: Path):
    settings_path = tmp_path / "settings.yml"
    settings_path.write_text(yaml.dump({"not_a_real_field": True}), encoding="utf-8")
    with pytest.raises(ValidationError):
        resolve_settings({}, settings_file=settings_path)


def test_settings_rejects_duplicate_key_in_settings_file(tmp_path: Path):
    """A duplicate key in the settings file fails loudly rather than silently
    keeping the last value."""
    settings_path = tmp_path / "settings.yml"
    settings_path.write_text(
        "warehouse_id: first\nwarehouse_id: second\n", encoding="utf-8"
    )
    with pytest.raises(DuplicateKeyError):
        resolve_settings({}, settings_file=settings_path)


def test_settings_loads_boolean_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_ENABLE_TAG_MANAGEMENT", "true")
    settings = resolve_settings({}, settings_file=None)
    assert settings.enable_tag_management is True


def test_settings_loads_enable_group_deletion_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_ENABLE_GROUP_DELETION", "true")
    settings = resolve_settings({}, settings_file=None)
    assert settings.enable_group_deletion is True


def test_settings_loads_namespace_scope_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_MANAGE_TAGS_FOR_NAMESPACES", "cat_env.sch1")
    settings = resolve_settings({}, settings_file=None)
    assert settings.manage_tags_for_namespaces == "cat_env.sch1"


def test_settings_loads_domain_modification_scopes_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_DOMAIN_MODIFICATION_SCOPES", "finance*")
    settings = resolve_settings({}, settings_file=None)
    assert settings.domain_modification_scopes == "finance*"


def test_settings_loads_domain_deletion_scopes_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_DOMAIN_DELETION_SCOPES", "finance*")
    settings = resolve_settings({}, settings_file=None)
    assert settings.domain_deletion_scopes == "finance*"


def test_settings_loads_domain_creation_scopes_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_DOMAIN_CREATION_SCOPES", "finance*")
    settings = resolve_settings({}, settings_file=None)
    assert settings.domain_creation_scopes == "finance*"


def test_settings_empty_retain_prefixes_env_clears_default(monkeypatch):
    monkeypatch.setenv("UC_ABAC_RETAIN_TAG_PREFIXES", "")
    settings = resolve_settings({}, settings_file=None)
    assert settings.retain_tag_prefixes == ""


def test_settings_empty_bool_env_does_not_override_default(monkeypatch):
    monkeypatch.setenv("UC_ABAC_ENABLE_TAG_MANAGEMENT", "")
    settings = resolve_settings({}, settings_file=None)
    assert settings.enable_tag_management is False


# ---------------------------------------------------------------------------
# timezone
# ---------------------------------------------------------------------------


def test_settings_timezone_defaults_to_utc_when_unset(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UC_ABAC_TIMEZONE", raising=False)
    settings = resolve_settings({}, settings_file=None)
    assert settings.timezone == "UTC"


@pytest.mark.parametrize(
    ("file_value", "env_value", "cli_value", "expected"),
    [
        pytest.param(None, None, None, "UTC", id="default"),
        pytest.param(
            "Australia/Melbourne", None, None, "Australia/Melbourne", id="settings-file"
        ),
        pytest.param(
            "Australia/Melbourne",
            "America/New_York",
            None,
            "America/New_York",
            id="environment-over-file",
        ),
        pytest.param(
            "Australia/Melbourne",
            "America/New_York",
            "Europe/London",
            "Europe/London",
            id="cli-over-environment",
        ),
    ],
)
def test_given_timezone_sources_when_settings_are_resolved_then_normal_precedence_applies(
    file_value: str | None,
    env_value: str | None,
    cli_value: str | None,
    expected: str,
    monkeypatch,
    tmp_path: Path,
):
    # Given
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UC_ABAC_TIMEZONE", raising=False)
    if file_value is not None:
        (tmp_path / "uc_abac.yml").write_text(
            yaml.dump({"timezone": file_value}), encoding="utf-8"
        )
    if env_value is not None:
        monkeypatch.setenv("UC_ABAC_TIMEZONE", env_value)
    cli_overrides = {"timezone": cli_value} if cli_value is not None else {}

    # When
    settings = resolve_settings(cli_overrides, settings_file=None)

    # Then
    assert settings.timezone == expected


def test_settings_loads_timezone_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_TIMEZONE", "Australia/Melbourne")
    settings = resolve_settings({}, settings_file=None)
    assert settings.timezone == "Australia/Melbourne"


def test_settings_accepts_valid_iana_timezone_from_file(tmp_path: Path):
    settings_path = tmp_path / "settings.yml"
    settings_path.write_text(
        yaml.dump({"timezone": "Australia/Melbourne"}), encoding="utf-8"
    )
    settings = resolve_settings({}, settings_file=settings_path)
    assert settings.timezone == "Australia/Melbourne"


def test_settings_rejects_unknown_timezone(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UC_ABAC_TIMEZONE", raising=False)
    with pytest.raises(ValidationError):
        resolve_settings({"timezone": "Not/AZone"}, settings_file=None)


# ---------------------------------------------------------------------------
# dump subcommand settings: target_schema
# ---------------------------------------------------------------------------


def test_settings_target_schema_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UC_ABAC_TARGET_SCHEMA", "main.state")
    settings = resolve_settings({}, settings_file=None)
    assert settings.target_schema == "main.state"


def test_settings_target_schema_from_file(tmp_path: Path):
    settings_path = tmp_path / "uc_abac.yml"
    settings_path.write_text(
        yaml.dump({"target_schema": "main.state"}), encoding="utf-8"
    )
    settings = resolve_settings({}, settings_file=settings_path)
    assert settings.target_schema == "main.state"


def test_settings_cli_target_schema_overrides_env(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UC_ABAC_TARGET_SCHEMA", "main.env_schema")
    settings = resolve_settings(
        {"target_schema": "main.cli_schema"},
        settings_file=None,
    )
    assert settings.target_schema == "main.cli_schema"


def test_settings_env_target_schema_overrides_file(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    settings_path = tmp_path / "uc_abac.yml"
    settings_path.write_text(
        yaml.dump({"target_schema": "main.file_schema"}), encoding="utf-8"
    )
    monkeypatch.setenv("UC_ABAC_TARGET_SCHEMA", "main.env_schema")
    settings = resolve_settings({}, settings_file=None)
    assert settings.target_schema == "main.env_schema"


def test_settings_loads_securable_modification_scopes_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_SECURABLE_MODIFICATION_SCOPES", "main.*")
    settings = resolve_settings({}, settings_file=None)
    assert settings.securable_modification_scopes == "main.*"


def test_settings_loads_securable_creation_scopes_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_SECURABLE_CREATION_SCOPES", "staging.*")
    settings = resolve_settings({}, settings_file=None)
    assert settings.securable_creation_scopes == "staging.*"


def test_settings_loads_legacy_taggable_scopes_from_settings_file(tmp_path: Path):
    settings_path = tmp_path / "uc_abac.yml"
    settings_path.write_text(
        yaml.dump(
            {
                "taggable_management_scopes": "main.*",
                "taggable_creation_scopes": "staging.*",
            }
        ),
        encoding="utf-8",
    )
    settings = resolve_settings({}, settings_file=settings_path)
    assert settings.taggable_management_scopes == "main.*"
    assert settings.taggable_creation_scopes == "staging.*"


def test_settings_loads_group_modification_scopes_from_env(monkeypatch):
    monkeypatch.setenv("UC_ABAC_GROUP_MODIFICATION_SCOPES", "team_*")
    settings = resolve_settings({}, settings_file=None)
    assert settings.group_modification_scopes == "team_*"


def test_settings_loads_legacy_management_scopes_from_settings_file(tmp_path: Path):
    settings_path = tmp_path / "uc_abac.yml"
    settings_path.write_text(
        yaml.dump(
            {
                "securable_management_scopes": "main.*",
                "group_management_scopes": "team_*",
                "domain_management_scopes": "fin*",
            }
        ),
        encoding="utf-8",
    )
    settings = resolve_settings({}, settings_file=settings_path)
    assert settings.securable_management_scopes == "main.*"
    assert settings.group_management_scopes == "team_*"
    assert settings.domain_management_scopes == "fin*"
