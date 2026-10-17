from __future__ import annotations

import re
from pathlib import Path

import pytest

from uc_declarative_abac.cli.parser import parse_cli_args

_SHARED_DEFAULT_ANNOTATIONS = (
    r"--system-catalog\b[\s\S]*?\[default: system\]",
    r"--ref-override-strategy\b[\s\S]*?\[default: merge\]",
    r"--max-parallel-changes\b[\s\S]*?\[default: 8\]",
)
_COMMAND_HELP_SECTIONS = ("USAGE:", "FLAGS:", "EXAMPLES:")


def _help_output(argv: list[str], capsys) -> str:
    with pytest.raises(SystemExit) as exc_info:
        parse_cli_args(argv)
    assert exc_info.value.code == 0
    return capsys.readouterr().out


def _assert_contains_patterns(output: str, patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        assert re.search(pattern, output)


def _example_commands(output: str, prefix: str) -> list[str]:
    return [
        line.strip() for line in output.splitlines() if line.strip().startswith(prefix)
    ]


def test_parser_displays_polished_root_help(capsys):
    output = _help_output(["--help"], capsys)
    nonempty_lines = [line for line in output.splitlines() if line.strip()]
    compact_header = " ".join(nonempty_lines[:3])
    assert "UC Declarative ABAC" in compact_header
    assert re.search(r"\bv?\d+\.\d+\.\d+\b", compact_header)

    for section in ("USAGE:", "COMMANDS:", "GLOBAL OPTIONS:", "EXAMPLES:"):
        assert section in output

    command_lines = [
        line
        for line in output.splitlines()
        if line.lstrip().startswith(("validate ", "deploy "))
    ]
    assert len(command_lines) == 2
    assert all(line.startswith("  ") for line in command_lines)
    description_columns = [
        re.search(r"\s{2,}\S", line[2:]).start() + 4 for line in command_lines
    ]
    assert len(set(description_columns)) == 1
    assert "validate" in output and "YAML" in output
    assert "deploy" in output and "Unity Catalog" in output

    examples = [line for line in output.splitlines() if line.startswith("  uc-abac ")]
    assert 2 <= len(examples) <= 3


def test_parser_displays_polished_validate_help(capsys):
    output = _help_output(["validate", "--help"], capsys)

    assert "Validate YAML configs locally" in output
    for section in _COMMAND_HELP_SECTIONS:
        assert section in output

    for flag in (
        "--config-dir",
        "--profile",
        "--system-catalog",
        "--ref-override-strategy",
        "--max-parallel-changes",
    ):
        assert flag in output

    _assert_contains_patterns(output, _SHARED_DEFAULT_ANNOTATIONS)

    examples = _example_commands(output, "uc-abac validate ")
    assert 2 <= len(examples) <= 3
    assert all("--config-dir" in example for example in examples)
    assert all(len(line) <= 80 for line in output.splitlines())


def test_parser_displays_polished_deploy_help(capsys):
    output = _help_output(["deploy", "--help"], capsys)

    assert "Deploy declarative governance to Unity Catalog" in output
    for section in _COMMAND_HELP_SECTIONS:
        assert section in output

    for flag in (
        "--config-dir",
        "--warehouse-id",
        "--dry-run",
        "--enable-tag-management",
        "--enable-privilege-management",
        "--enable-policy-deletion",
        "--enable-group-deletion",
        "--manage-tags-for-namespaces",
        "--delete-policies-for-namespaces",
    ):
        assert flag in output

    _assert_contains_patterns(output, _SHARED_DEFAULT_ANNOTATIONS)
    assert "Off by default" in output

    examples = _example_commands(output, "uc-abac deploy ")
    assert 2 <= len(examples) <= 3
    assert all("--config-dir" in example for example in examples)
    assert any("--dry-run" in example for example in examples)
    assert any("--dry-run" not in example for example in examples)
    assert all(len(line) <= 80 for line in output.splitlines())


def test_parser_help_documents_domain_management_behavior(capsys):
    output = _help_output(["deploy", "--help"], capsys)
    help_text = " ".join(output.split())

    assert "--domain-modification-scopes" in output
    assert "explicitly declared resources.domains" in help_text
    assert "by governed-tag key" in help_text
    assert re.search(r"Comma-\s*separated names", output)
    assert "Empty (default) disables the feature" in help_text
    assert "'*' covers all" in help_text
    assert "a trailing '*' is a raw name prefix" in help_text
    assert "any other entry is an exact name" in help_text


def test_parser_help_documents_domain_deletion_scopes_behavior(capsys):
    output = _help_output(["deploy", "--help"], capsys)
    help_text = " ".join(output.split())

    assert "--domain-deletion-scopes" in output
    assert "domain deletion" in help_text
    assert "matching domains (by governed-tag key)" in help_text
    assert "Requires interactive confirmation unless --force is set." in help_text


def test_parser_displays_timezone_flag_in_validate_help(capsys):
    output = _help_output(["validate", "--help"], capsys)
    assert "--timezone" in output


def test_parser_displays_timezone_flag_in_deploy_help(capsys):
    output = _help_output(["deploy", "--help"], capsys)
    assert "--timezone" in output


@pytest.mark.parametrize(
    "args",
    [
        [
            "deploy",
            "--config-dir",
            "cfg",
            "--warehouse-id",
            "wh",
            "--timezone",
            "Australia/Melbourne",
        ],
        [
            "--config-dir",
            "cfg",
            "--warehouse-id",
            "wh",
            "--timezone",
            "Australia/Melbourne",
        ],
    ],
    ids=["modern-deploy", "legacy-invocation"],
)
def test_parser_accepts_timezone_for_deploy_invocations(args):
    namespace = parse_cli_args(args)
    assert namespace.timezone == "Australia/Melbourne"


def test_parser_reports_actionable_error_when_command_is_unknown(capsys):
    with pytest.raises(SystemExit) as exc_info:
        parse_cli_args(["unknown"])

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "✖" in error or "[ERROR]" in error
    assert re.search(r"unknown|invalid command", error, re.IGNORECASE)
    assert "uc-abac --help" in error
    assert "COMMANDS:" not in error
    assert "EXAMPLES:" not in error


def test_parser_routes_deploy_to_execute():
    namespace = parse_cli_args(
        ["deploy", "--config-dir", "cfg", "--warehouse-id", "wh"],
    )
    assert namespace.command == "deploy"
    assert getattr(namespace, "dry_run", False) is False


def test_parser_deploy_dry_run_sets_flag():
    namespace = parse_cli_args(
        ["deploy", "--config-dir", "cfg", "--warehouse-id", "wh", "--dry-run"],
    )
    assert namespace.command == "deploy"
    assert namespace.dry_run is True


def test_parser_accepts_domain_modification_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            "--domain-modification-scopes",
            "finance*",
        ],
    )

    assert namespace.domain_modification_scopes == "finance*"

    with pytest.raises(SystemExit) as exc_info:
        parse_cli_args(
            [
                "deploy",
                "--config-dir",
                "/tmp/configs",
                "--warehouse-id",
                "wh",
                "--enable-domain-management",
            ]
        )
    assert exc_info.value.code == 2


def test_parser_accepts_domain_deletion_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "cfg",
            "--warehouse-id",
            "wh",
            "--domain-deletion-scopes",
            "finance*",
        ],
    )

    assert namespace.domain_deletion_scopes == "finance*"


def test_parser_accepts_domain_creation_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "cfg",
            "--warehouse-id",
            "wh",
            "--domain-creation-scopes",
            "finance*",
        ],
    )

    assert namespace.domain_creation_scopes == "finance*"


def test_parser_legacy_dry_run_maps_to_deploy():
    namespace = parse_cli_args(
        ["--config-dir", "cfg", "--warehouse-id", "wh", "--dry-run"],
    )
    assert namespace.command == "deploy"
    assert namespace.dry_run is True
    assert namespace.legacy is True


def test_parser_legacy_without_dry_run_maps_to_deploy():
    namespace = parse_cli_args(
        ["--config-dir", "cfg", "--warehouse-id", "wh"],
    )
    assert namespace.command == "deploy"
    assert getattr(namespace, "dry_run", False) is False
    assert namespace.legacy is True


@pytest.mark.parametrize(
    "args",
    [
        [
            "deploy",
            "--config-dir",
            "cfg",
            "--warehouse-id",
            "wh",
            "--system-catalog",
            "system",
        ],
        ["--config-dir", "cfg", "--warehouse-id", "wh", "--system-catalog", "system"],
    ],
    ids=["modern-deploy", "legacy-invocation"],
)
def test_parser_accepts_system_catalog_for_deploy_invocations(args):
    namespace = parse_cli_args(args)

    assert namespace.system_catalog == "system"


def test_parser_global_flag_before_subcommand_is_not_legacy():
    namespace = parse_cli_args(
        ["--verbose", "deploy", "--config-dir", "cfg", "--warehouse-id", "wh"],
    )
    assert namespace.command == "deploy"
    assert namespace.legacy is False


def test_parser_value_taking_global_flag_before_subcommand_is_not_legacy(tmp_path):
    settings_file = tmp_path / "s.yml"
    settings_file.write_text("config_dir: cfg\n", encoding="utf-8")
    namespace = parse_cli_args(
        ["--settings-file", str(settings_file), "validate"],
    )
    assert namespace.command == "validate"
    assert namespace.legacy is False


def test_parser_global_flag_before_legacy_flags_stays_legacy():
    namespace = parse_cli_args(
        ["--verbose", "--config-dir", "cfg", "--warehouse-id", "wh"],
    )
    assert namespace.command == "deploy"
    assert namespace.legacy is True


def test_cli_reports_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        parse_cli_args(["--version"])
    assert exc_info.value.code == 0


# ---
# dump subcommand
# ---


def test_parser_dump_routing_and_basic_flags():
    namespace = parse_cli_args(
        [
            "dump",
            "--config-dir",
            "c",
            "--warehouse-id",
            "w",
            "--target-schema",
            "main.state",
        ]
    )
    assert namespace.command == "dump"
    assert namespace.config_dir == Path("c")
    assert namespace.warehouse_id == "w"
    assert namespace.target_schema == "main.state"
    assert namespace.legacy is False


def test_parser_dump_help_includes_required_flags(capsys):
    output = _help_output(["dump", "--help"], capsys)

    for flag in (
        "--config-dir",
        "--warehouse-id",
        "--target-schema",
        "--profile",
        "--system-catalog",
        "--max-parallel-changes",
        "--dry-run",
    ):
        assert flag in output


def test_parser_dump_help_excludes_deploy_only_flags(capsys):
    output = _help_output(["dump", "--help"], capsys)

    for flag in (
        "--enable-tag-management",
        "--tag-management-scopes",
        "--force",
        "--retain-tag-prefixes",
        "--use-workspace-scim",
        "--skip-users-fetch",
        "--ref-override-strategy",
    ):
        assert flag not in output


def test_parser_root_help_mentions_dump(capsys):
    output = _help_output(["--help"], capsys)
    dump_lines = [
        line for line in output.splitlines() if line.lstrip().startswith("dump ")
    ]
    assert len(dump_lines) >= 1
    assert any("dump" in line.lower() for line in dump_lines)


def test_parser_displays_timezone_flag_in_dump_help(capsys):
    output = _help_output(["dump", "--help"], capsys)
    assert "--timezone" in output


@pytest.mark.parametrize(
    "args",
    [
        [
            "dump",
            "--config-dir",
            "cfg",
            "--warehouse-id",
            "wh",
            "--target-schema",
            "main.state",
            "--timezone",
            "Pacific/Kiritimati",
        ],
    ],
    ids=["dump-with-timezone"],
)
def test_parser_accepts_timezone_for_dump_invocations(args):
    namespace = parse_cli_args(args)
    assert namespace.timezone == "Pacific/Kiritimati"


def test_parser_dump_accepts_replace_tables_flag():
    namespace = parse_cli_args(
        [
            "dump",
            "--config-dir",
            "cfg",
            "--warehouse-id",
            "wh",
            "--target-schema",
            "main.state",
            "--replace-tables",
        ]
    )
    assert namespace.replace_tables is True


def test_parser_dump_help_includes_replace_tables_flag(capsys):
    output = _help_output(["dump", "--help"], capsys)
    assert "--replace-tables" in output


def test_parser_deploy_does_not_accept_replace_tables_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        parse_cli_args(
            [
                "deploy",
                "--config-dir",
                "cfg",
                "--warehouse-id",
                "wh",
                "--replace-tables",
            ]
        )
    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "replace-tables" in error or "unrecognized arguments" in error


def test_parser_accepts_securable_modification_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            "--securable-modification-scopes",
            "main.*",
        ],
    )

    assert namespace.securable_modification_scopes == "main.*"


def test_parser_accepts_securable_creation_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            "--securable-creation-scopes",
            "main.*",
        ],
    )

    assert namespace.securable_creation_scopes == "main.*"


def test_parser_help_documents_securable_scopes_do_not_gate_functions(capsys):
    output = _help_output(["deploy", "--help"], capsys)
    # Normalize whitespace for easier substring checking
    help_text = " ".join(output.split())

    assert "--securable-modification-scopes" in output
    assert "--securable-creation-scopes" in output
    assert "function" in help_text
    assert "columns" in help_text
    assert "does not gate function" in help_text.lower()


def test_parser_help_marks_taggable_scopes_deprecated(capsys):
    output = _help_output(["deploy", "--help"], capsys)

    assert "--taggable-management-scopes" in output
    assert "--taggable-creation-scopes" in output
    assert re.search(
        r"--taggable-management-scopes[\s\S]*?\(Deprecated.*--securable-modification-scopes",
        output,
    )
    assert re.search(
        r"--taggable-creation-scopes[\s\S]*?\(Deprecated.*--securable-creation-scopes",
        output,
    )


def test_parser_still_accepts_legacy_taggable_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            "--taggable-management-scopes",
            "main.*",
        ],
    )

    assert namespace.taggable_management_scopes == "main.*"

    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            "--taggable-creation-scopes",
            "staging.*",
        ],
    )

    assert namespace.taggable_creation_scopes == "staging.*"


def test_parser_accepts_group_modification_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            "--group-modification-scopes",
            "team_*",
        ],
    )

    assert namespace.group_modification_scopes == "team_*"


def test_parser_help_documents_modification_scopes_never_create_or_delete(capsys):
    output = _help_output(["deploy", "--help"], capsys)
    help_text = " ".join(output.split())

    # Check that the three modification scopes flags are present
    assert "--securable-modification-scopes" in output
    assert "--group-modification-scopes" in output
    assert "--domain-modification-scopes" in output

    # Check that help says updates only / never creates or deletes
    # (loose: the normalised help contains "never creates or deletes" at least 3 times)
    assert help_text.count("never creates or deletes") >= 3


def test_parser_help_marks_management_scopes_deprecated(capsys):
    output = _help_output(["deploy", "--help"], capsys)

    # Check that deprecated management scopes are marked as deprecated
    assert re.search(
        r"--securable-management-scopes[\s\S]*?\(Deprecated.*--securable-modification-scopes",
        output,
    )
    assert re.search(
        r"--group-management-scopes[\s\S]*?\(Deprecated.*--group-modification-scopes",
        output,
    )
    assert re.search(
        r"--domain-management-scopes[\s\S]*?\(Deprecated.*--domain-modification-scopes",
        output,
    )


@pytest.mark.parametrize(
    ("flag", "value", "attr"),
    [
        ("--securable-management-scopes", "main.*", "securable_management_scopes"),
        ("--group-management-scopes", "team_*", "group_management_scopes"),
        ("--domain-management-scopes", "fin*", "domain_management_scopes"),
    ],
)
def test_parser_still_accepts_legacy_management_scopes(flag, value, attr):
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            flag,
            value,
        ],
    )

    assert getattr(namespace, attr) == value


def test_parser_help_keeps_tag_and_privilege_management_scopes(capsys):
    output = _help_output(["deploy", "--help"], capsys)

    # Check that tag and privilege management scopes are present
    assert "--tag-management-scopes" in output
    assert "--privilege-management-scopes" in output

    # Check they are NOT marked as deprecated (by making sure the word
    # "Deprecated" does not appear near them)
    assert not re.search(
        r"--tag-management-scopes[\s\S]{0,100}\(Deprecated",
        output,
    )
    assert not re.search(
        r"--privilege-management-scopes[\s\S]{0,100}\(Deprecated",
        output,
    )


def test_parser_accepts_tag_assignment_scopes():
    namespace = parse_cli_args(
        [
            "deploy",
            "--config-dir",
            "/tmp/configs",
            "--warehouse-id",
            "wh",
            "--tag-assignment-scopes",
            "main.sales*",
        ],
    )

    assert namespace.tag_assignment_scopes == "main.sales*"


def test_parser_help_documents_tag_assignment_scopes_never_remove(capsys):
    output = _help_output(["deploy", "--help"], capsys)
    # Normalize whitespace for easier substring checking
    help_text = " ".join(output.split())

    assert "--tag-assignment-scopes" in output
    assert "Never removes tags" in help_text
