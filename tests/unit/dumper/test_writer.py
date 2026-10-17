"""Tests for uc_abac.dumper.writer (dump_state function)."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from databricks.sdk.errors import NotFound, PermissionDenied

from uc_abac import ActualState
from uc_abac.configs import ResourcesConfig
from uc_abac.dumper import (
    INSERT_MAX_ROWS,
    TABLE_SPECS,
    TARGET_SCHEMA_COMMENT,
    build_create_table_sql,
    build_overwrite_from_sql,
    dump_state,
)
from uc_abac.securables import Securable
from uc_abac.types import SecurableType
from uc_abac.utils import ExecutionBatchError, sql_string_literal

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _build_minimal_config_dir(tmp_path: Path) -> Path:
    """Build a minimal valid config directory in tmp_path."""
    config = {"resources": {"catalogs": {"main": {}}}}
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config, default_flow_style=False))
    return tmp_path


def _build_minimal_actual_state() -> ActualState:
    """Build a minimal ActualState with all required fields."""
    return ActualState(
        groups=frozenset(),
        all_account_groups=frozenset(),
        governed_tags=frozenset(),
        domains=frozenset(),
        securables=frozenset(),
        attributes=frozenset(),
        tags=frozenset(),
        policies=frozenset(),
        privileges=frozenset(),
        principals={},
    )


def _normalize_sql_backticks(sql: str) -> str:
    """Remove all backticks from SQL to make comparisons lenient."""
    return sql.replace("`", "")


def _existing_tables(mock_workspace_client: MagicMock, *names: str) -> None:
    """Mark a set of table names as existing in the target schema.

    Sets mock_workspace_client.tables.list.return_value to return SimpleNamespace
    objects with .name set to each provided name. Used to signal to dump_state that
    these tables should be treated as existing and eligible for schema evolution swap.
    """
    mock_workspace_client.tables.list.return_value = [
        SimpleNamespace(name=name) for name in names
    ]


def _mark_all_tables_as_existing(mock_workspace_client: MagicMock) -> None:
    """Mark all TABLE_SPECS tables as existing."""
    _existing_tables(mock_workspace_client, *[spec.name for spec in TABLE_SPECS])


# ---
# CREATE TABLE and INSERT statement tests
# ---


def test_dumper_writer_creates_one_table_per_spec(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """dump_state creates one staging CREATE OR REPLACE TABLE and one swap per TABLE_SPECS table."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # Check that we have one staging CREATE for each table
    create_statements = [
        sql
        for sql in mock_workspace_client.executed_sql
        if "CREATE OR REPLACE TABLE" in sql and "_tmp_" in sql
    ]
    assert len(create_statements) == len(TABLE_SPECS), (
        f"Expected {len(TABLE_SPECS)} staging CREATE statements, got {len(create_statements)}"
    )

    # Check that each staging table name appears in the CREATE statements
    normalized_creates = [_normalize_sql_backticks(sql) for sql in create_statements]
    for spec in TABLE_SPECS:
        staging_full_name = f"main.state._tmp_{spec.name}"
        assert any(
            staging_full_name in normalized for normalized in normalized_creates
        ), f"Staging table {staging_full_name} not found in CREATE statements"


def test_dumper_writer_writes_pseudo_policies_table(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state creates the staging pseudo_policies table with CREATE OR REPLACE TABLE."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # Check that CREATE OR REPLACE TABLE for pseudo_policies staging is executed
    normalized_stmts = [
        _normalize_sql_backticks(sql) for sql in mock_workspace_client.executed_sql
    ]
    pseudo_policies_creates = [
        s
        for s in normalized_stmts
        if "CREATE OR REPLACE TABLE main.state._tmp_pseudo_policies" in s
    ]
    assert len(pseudo_policies_creates) == 1, (
        f"Expected exactly one CREATE for pseudo_policies staging table, got {len(pseudo_policies_creates)}"
    )


def test_dumper_writer_create_precedes_inserts(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state ensures each table's CREATE precedes that table's INSERTs."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    sql_statements = mock_workspace_client.executed_sql
    normalized_stmts = [_normalize_sql_backticks(sql) for sql in sql_statements]

    for spec in TABLE_SPECS:
        table_full_name = f"main.state.{spec.name}"
        create_idx = None
        insert_indices = []

        for i, stmt in enumerate(normalized_stmts):
            if f"CREATE OR REPLACE TABLE {table_full_name}" in stmt:
                create_idx = i
            if f"INSERT INTO {table_full_name}" in stmt:
                insert_indices.append(i)

        if insert_indices:
            # If there are INSERT statements, CREATE must come first
            assert create_idx is not None, (
                f"No CREATE found for table {table_full_name} which has INSERTs"
            )
            assert create_idx < min(insert_indices), (
                f"CREATE for {table_full_name} at index {create_idx} "
                f"comes after INSERT at index {min(insert_indices)}"
            )


def test_dumper_writer_empty_domain_creates_table_without_insert(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state handles a table with no rows: staging CREATE, swap, no INSERT batches."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        # All tables have empty row sets
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    sql_statements = mock_workspace_client.executed_sql
    normalized_stmts = [_normalize_sql_backticks(sql) for sql in sql_statements]

    # The domains table should have a staging CREATE but no INSERT (since state has no domains)
    domains_creates = [
        s
        for s in normalized_stmts
        if "CREATE OR REPLACE TABLE main.state._tmp_domains" in s
    ]
    domains_inserts = [
        s for s in normalized_stmts if "INSERT INTO main.state._tmp_domains" in s
    ]

    assert len(domains_creates) == 1, (
        "Should have exactly one CREATE for domains staging table"
    )
    assert len(domains_inserts) == 0, (
        "Should have no INSERT batches for empty domains table"
    )


def test_dumper_writer_multiple_inserts_when_exceeding_max_rows(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state chunks INSERT statements into staging when row count exceeds INSERT_MAX_ROWS."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        # Build a state with many securables (>INSERT_MAX_ROWS)
        num_securables = INSERT_MAX_ROWS * 2 + 500  # 2500 with default 1000
        securables = frozenset(
            Securable(SecurableType.CATALOG, f"c{i}") for i in range(num_securables)
        )
        state = ActualState(
            groups=frozenset(),
            all_account_groups=frozenset(),
            governed_tags=frozenset(),
            domains=frozenset(),
            securables=securables,
            attributes=frozenset(),
            tags=frozenset(),
            policies=frozenset(),
            privileges=frozenset(),
            principals={},
        )
        mock_fetch.return_value = state

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    sql_statements = mock_workspace_client.executed_sql
    normalized_stmts = [_normalize_sql_backticks(sql) for sql in sql_statements]

    # Find all INSERT statements for securables staging table
    securables_inserts = [
        s
        for s in normalized_stmts
        if "INSERT INTO main.state._tmp_securables " in s
        or "INSERT INTO main.state._tmp_securables(" in s
    ]

    # With 2500 rows and INSERT_MAX_ROWS=1000, we expect exactly 3 INSERT statements
    assert len(securables_inserts) == 3, (
        f"Expected exactly 3 INSERT statements for securables staging "
        f"(2500 rows / 1000 max), got {len(securables_inserts)}"
    )


# ---
# Schema creation tests
# ---


def test_dumper_writer_schema_exists_no_create_schema(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state skips CREATE SCHEMA when the schema already exists."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # No CREATE SCHEMA should be issued
    create_schema_stmts = [
        sql
        for sql in mock_workspace_client.executed_sql
        if "CREATE SCHEMA" in sql.upper()
    ]
    assert len(create_schema_stmts) == 0, (
        f"Expected no CREATE SCHEMA, but found: {create_schema_stmts}"
    )


def test_dumper_writer_schema_missing_creates_schema(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state creates the schema when it doesn't exist (NotFound error)."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.side_effect = NotFound("schema not found")

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # Should have exactly one CREATE SCHEMA statement
    create_schema_stmts = [
        sql
        for sql in mock_workspace_client.executed_sql
        if "CREATE SCHEMA" in sql.upper()
    ]
    assert len(create_schema_stmts) == 1, (
        f"Expected exactly one CREATE SCHEMA, got {len(create_schema_stmts)}: "
        f"{create_schema_stmts}"
    )

    # Verify it doesn't use IF NOT EXISTS
    schema_sql = create_schema_stmts[0].upper()
    assert "IF NOT EXISTS" not in schema_sql, (
        "CREATE SCHEMA should not use IF NOT EXISTS"
    )


def test_dumper_writer_create_schema_before_create_tables(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state executes CREATE SCHEMA before any CREATE OR REPLACE TABLE."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.side_effect = NotFound("schema not found")

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    sql_statements = mock_workspace_client.executed_sql

    create_schema_idx = None
    first_create_table_idx = None

    for i, sql in enumerate(sql_statements):
        if "CREATE SCHEMA" in sql.upper() and create_schema_idx is None:
            create_schema_idx = i
        if "CREATE OR REPLACE TABLE" in sql and first_create_table_idx is None:
            first_create_table_idx = i

    assert create_schema_idx is not None, (
        "CREATE SCHEMA not found in executed statements"
    )
    assert first_create_table_idx is not None, (
        "CREATE OR REPLACE TABLE not found in executed statements"
    )
    assert create_schema_idx < first_create_table_idx, (
        "CREATE SCHEMA should execute before CREATE OR REPLACE TABLE"
    )


def test_dumper_writer_schemas_get_before_fetch_actual_state(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state checks schema existence before calling fetch_actual_state."""
    config_dir = _build_minimal_config_dir(tmp_path)
    call_order = []

    def track_schemas_get(*args, **kwargs):
        call_order.append("schemas_get")
        raise NotFound("schema not found")

    mock_workspace_client.schemas.get.side_effect = track_schemas_get

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:

        def track_fetch(*args, **kwargs):
            call_order.append("fetch_actual_state")
            return _build_minimal_actual_state()

        mock_fetch.side_effect = track_fetch

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    assert call_order == ["schemas_get", "fetch_actual_state"], (
        f"Expected schemas_get before fetch_actual_state, got: {call_order}"
    )


def test_dumper_writer_non_notfound_error_from_schemas_get_propagates(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state propagates non-NotFound errors from schemas.get and doesn't call fetch_actual_state."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.side_effect = PermissionDenied("no access")

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        with pytest.raises(PermissionDenied):
            dump_state(
                mock_workspace_client,
                config_dir=config_dir,
                warehouse_id="warehouse-1",
                target_schema="main.state",
            )

    # fetch_actual_state should not have been called
    mock_fetch.assert_not_called()


# ---
# Dry run tests
# ---


def test_dumper_writer_dry_run_executes_no_sql(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state with dry_run=True executes no SQL at all."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.side_effect = NotFound("schema not found")

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
            dry_run=True,
        )

    assert len(mock_workspace_client.executed_sql) == 0, (
        "Dry run should execute no SQL statements"
    )


def test_dumper_writer_dry_run_logs_would_create_schema(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """dump_state with dry_run=True logs about the schema it would create."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.side_effect = NotFound("schema not found")

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        with caplog.at_level(logging.INFO):
            dump_state(
                mock_workspace_client,
                config_dir=config_dir,
                warehouse_id="warehouse-1",
                target_schema="main.state",
                dry_run=True,
            )

    # Log should mention "Would create" and the schema name
    log_text = caplog.text
    assert "Would create" in log_text, (
        f"Expected 'Would create' in log, got: {caplog.text}"
    )
    assert "main.state" in log_text, (
        f"Expected 'main.state' schema name in log, got: {caplog.text}"
    )


# ---
# Failure handling tests
# ---


def test_dumper_writer_failing_table_continues_other_tables(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state continues processing other tables when one table fails."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    original_side_effect = (
        mock_workspace_client.statement_execution.execute_statement.side_effect
    )

    def fail_on_securable_tags(*args, **kwargs):
        statement = kwargs.get("statement", args[0] if args else "")
        # Match precisely: securable_tags staging table
        if "main.state._tmp_securable_tags" in _normalize_sql_backticks(statement):
            raise RuntimeError("securable_tags table failed")
        # Use original side effect for other statements
        return original_side_effect(*args, **kwargs)

    mock_workspace_client.statement_execution.execute_statement.side_effect = (
        fail_on_securable_tags
    )

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        with pytest.raises(ExecutionBatchError) as exc_info:
            dump_state(
                mock_workspace_client,
                config_dir=config_dir,
                warehouse_id="warehouse-1",
                target_schema="main.state",
            )

        # The error should mention the failed table
        assert "securable_tags" in str(exc_info.value).lower()

    # Every OTHER table (all except securable_tags) should have staging CREATE executed
    sql_statements = mock_workspace_client.executed_sql
    normalized_stmts = [_normalize_sql_backticks(sql) for sql in sql_statements]

    for spec in TABLE_SPECS:
        if spec.name != "securable_tags":
            # Check that this table has a staging CREATE statement
            staging_name = f"main.state._tmp_{spec.name}"
            has_create = any(
                f"CREATE OR REPLACE TABLE {staging_name} " in stmt
                or f"CREATE OR REPLACE TABLE {staging_name}(" in stmt
                for stmt in normalized_stmts
            )
            assert has_create, (
                f"Table {spec.name} should have staging CREATE executed "
                f"even though another table failed"
            )


def test_dumper_writer_failing_table_raises_execution_batch_error(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state raises ExecutionBatchError naming the failed table(s)."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    original_side_effect = (
        mock_workspace_client.statement_execution.execute_statement.side_effect
    )

    def fail_on_securables(*args, **kwargs):
        statement = kwargs.get("statement", args[0] if args else "")
        # Match precisely: staging table creation for securables
        normalized = _normalize_sql_backticks(statement)
        if (
            "main.state._tmp_securables " in normalized
            and "CREATE OR REPLACE" in normalized
        ):
            raise RuntimeError("securables table staging creation failed")
        # Use original side effect for other statements
        return original_side_effect(*args, **kwargs)

    mock_workspace_client.statement_execution.execute_statement.side_effect = (
        fail_on_securables
    )

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        with pytest.raises(ExecutionBatchError) as exc_info:
            dump_state(
                mock_workspace_client,
                config_dir=config_dir,
                warehouse_id="warehouse-1",
                target_schema="main.state",
            )

        error = exc_info.value
        assert isinstance(error, ExecutionBatchError)
        # Assert "securables" is in the error (the failed table name)
        error_text = str(error).lower()
        assert "securables" in error_text, (
            f"Error should mention 'securables' table, got: {error_text}"
        )
        # Verify other tables don't appear as failures
        assert (
            "securable_tags" not in error_text
            or "securable_tags" not in error_text.split("securables")[0]
        ), f"Error should not list securable_tags as failed, got: {error_text}"


# ---
# Logging tests
# ---


def test_dumper_writer_logs_writing_and_wrote_per_table(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """dump_state logs a 'Writing to' and a 'Wrote to' line per table."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        with caplog.at_level(logging.INFO):
            dump_state(
                mock_workspace_client,
                config_dir=config_dir,
                warehouse_id="warehouse-1",
                target_schema="main.state",
            )

    log_text = caplog.text
    for spec in TABLE_SPECS:
        writing_found = False
        wrote_found = False
        for record in caplog.records:
            if "Writing to" in record.message and spec.name in record.message:
                writing_found = True
            if "Wrote to" in record.message and spec.name in record.message:
                wrote_found = True
        assert writing_found, (
            f"Expected 'Writing to' log for '{spec.name}', got: {log_text}"
        )
        assert wrote_found, (
            f"Expected 'Wrote to' log for '{spec.name}', got: {log_text}"
        )


# ---
# Configuration and helpers passing tests
# ---


def test_dumper_writer_passes_config_and_helpers_to_fetch(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state passes loaded config and helpers to fetch_actual_state without RunContext."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # Verify fetch_actual_state was called exactly once
    assert mock_fetch.call_count == 1

    # Get the call arguments
    call_args = mock_fetch.call_args
    # Should be 3 positional args: config, uc_helper, ws_helper
    # And the 4th arg (settings) should be None or not passed
    assert call_args is not None
    args, kwargs = call_args
    assert len(args) >= 3, f"Expected at least 3 positional args, got {len(args)}"

    # First arg should be the loaded config (ResourcesConfig)
    config_arg = args[0]
    assert isinstance(config_arg, ResourcesConfig), (
        f"First arg should be ResourcesConfig, got {type(config_arg)}"
    )
    # Check that the config has the catalogs from the YAML
    assert config_arg.catalogs is not None, "Config should have catalogs"
    assert "main" in config_arg.catalogs, (
        f"Config catalogs should include 'main', got: {list(config_arg.catalogs.keys())}"
    )

    # 4th argument (settings in kwargs or as positional arg) should be None or not present
    if len(args) > 3:
        # settings passed as positional arg
        settings = args[3]
        assert settings is None, f"Expected settings to be None, got {settings}"
    elif "settings" in kwargs:
        # settings passed as keyword arg
        settings = kwargs["settings"]
        assert settings is None, f"Expected settings to be None, got {settings}"


# ---
# Parallelism tests
# ---


def test_dumper_writer_with_default_parallelism(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state uses default max_parallel_tables unless overridden."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        # Call without max_parallel_tables parameter
        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # Should complete without error and execute statements
    assert len(mock_workspace_client.executed_sql) >= len(TABLE_SPECS)


# ---------------------------------------------------------------------------
# Table existence listing behavior (tables.list)
# ---------------------------------------------------------------------------


def _swap_statements(mock_workspace_client: MagicMock, table: str) -> list[str]:
    """Normalised statements that create or overwrite the target ``main.state.<table>``."""
    target = f"main.state.{table} "
    return [
        sql
        for sql in map(_normalize_sql_backticks, mock_workspace_client.executed_sql)
        if f"TABLE {target}" in sql or f"OVERWRITE {target}" in sql
    ]


def test_dumper_writer_recreates_a_missing_table_without_attempting_schema_evolution(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """A target table that doesn't exist yet is created and loaded straight away: no
    schema-evolution swap is attempted and no fallback warning is logged."""
    _existing_tables(mock_workspace_client)

    with caplog.at_level(logging.WARNING):
        _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    staging = "main.state._tmp_securables"
    assert _swap_statements(mock_workspace_client, "securables") == [
        _normalize_sql_backticks(
            build_create_table_sql(
                "main.state.securables",
                next(spec for spec in TABLE_SPECS if spec.name == "securables"),
            )
        ),
        _normalize_sql_backticks(
            build_overwrite_from_sql(
                "main.state.securables", staging, schema_evolution=False
            )
        ),
    ]
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_dumper_writer_swaps_an_existing_table_with_schema_evolution(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """Only a target table that already exists gets the schema-evolution swap; a
    missing one in the same run is created instead."""
    _existing_tables(mock_workspace_client, "securables")

    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    securables = _swap_statements(mock_workspace_client, "securables")
    domains = _swap_statements(mock_workspace_client, "domains")
    assert len(securables) == 1 and "WITH SCHEMA EVOLUTION" in securables[0]
    assert len(domains) == 2 and domains[0].startswith("CREATE OR REPLACE TABLE")
    assert not any("WITH SCHEMA EVOLUTION" in sql for sql in domains)


def test_dumper_writer_matches_existing_tables_case_insensitively(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """An existing table listed under a different case still counts as existing."""
    _existing_tables(mock_workspace_client, "SECURABLES")

    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    securables = _swap_statements(mock_workspace_client, "securables")
    assert len(securables) == 1 and "WITH SCHEMA EVOLUTION" in securables[0]


def test_dumper_writer_does_not_list_tables_when_target_schema_is_created(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """When the target schema is created by this run, its tables aren't listed and
    every table is created without a schema-evolution attempt."""
    mock_workspace_client.schemas.get.side_effect = NotFound("schema not found")

    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    mock_workspace_client.tables.list.assert_not_called()
    for spec in TABLE_SPECS:
        statements = _swap_statements(mock_workspace_client, spec.name)
        assert len(statements) == 2, spec.name
        assert not any("WITH SCHEMA EVOLUTION" in sql for sql in statements)


def test_dumper_writer_lists_target_tables_once(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state lists the existing target schema's tables once per run."""
    _existing_tables(mock_workspace_client)

    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    mock_workspace_client.tables.list.assert_called_once()
    kwargs = mock_workspace_client.tables.list.call_args.kwargs
    assert (kwargs["catalog_name"], kwargs["schema_name"]) == ("main", "state")


# ---------------------------------------------------------------------------
# Staging table behavior
# ---------------------------------------------------------------------------


def _fail_statements_matching(
    mock_workspace_client: MagicMock, predicate, message: str = "insert failed"
) -> None:
    """Make every statement whose backtick-normalised SQL matches ``predicate`` raise,
    while still recording it in ``executed_sql``. Optional ``message`` customizes the error."""
    original = mock_workspace_client.statement_execution.execute_statement.side_effect

    def _side_effect(*args, **kwargs):
        statement = kwargs.get("statement", args[0] if args else "")
        if predicate(_normalize_sql_backticks(statement)):
            mock_workspace_client.executed_sql.append(statement)
            raise RuntimeError(message)
        return original(*args, **kwargs)

    mock_workspace_client.statement_execution.execute_statement.side_effect = (
        _side_effect
    )


def _state_with_securables(count: int) -> ActualState:
    securables = frozenset(
        Securable(SecurableType.CATALOG, f"c{i}") for i in range(count)
    )
    return ActualState(
        **{**_build_minimal_actual_state().__dict__, "securables": securables}
    )


def _dump(
    mock_workspace_client: MagicMock,
    tmp_path: Path,
    state: ActualState,
    max_parallel_tables: int = 1,
):
    with patch("uc_abac.dumper.writer.fetch_actual_state", return_value=state):
        dump_state(
            mock_workspace_client,
            config_dir=_build_minimal_config_dir(tmp_path),
            warehouse_id="warehouse-1",
            target_schema="main.state",
            max_parallel_tables=max_parallel_tables,
        )


def test_dumper_writer_creates_staging_table(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state creates staging tables _tmp_<table> for each target table."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # Check for staging table creates
    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    for spec in TABLE_SPECS:
        staging_name = f"main.state._tmp_{spec.name}"
        has_staging_create = any(
            f"CREATE OR REPLACE TABLE {staging_name}" in s for s in statements
        )
        assert has_staging_create, f"Expected CREATE for staging table {staging_name}"


def test_dumper_writer_inserts_into_staging_table(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state inserts rows into staging tables, not target tables."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    securables_inserts = [
        s for s in statements if "INSERT INTO main.state.securables " in s
    ]
    staging_inserts = [
        s for s in statements if "INSERT INTO main.state._tmp_securables " in s
    ]

    # Should have inserts into staging table
    assert len(staging_inserts) > 0, "Should have inserts into staging table"
    # Should not have inserts into target table
    assert len(securables_inserts) == 0, "Should not insert into target table directly"


def test_dumper_writer_drops_staging_table_after_success(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state drops staging tables after successful swap."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    drops = [
        s
        for s in statements
        if s.strip() == "DROP TABLE IF EXISTS main.state._tmp_securables"
    ]
    assert len(drops) == 1, "Should drop staging table after swap"


def test_dumper_writer_staging_insert_failure_does_not_touch_target(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """A failed INSERT into staging never touches the target table."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: (
            sql.startswith("INSERT INTO main.state._tmp_securables ")
            and "'c150'" in sql
        ),
    )

    with pytest.raises(ExecutionBatchError, match="main.state.securables"):
        _dump(
            mock_workspace_client, tmp_path, _state_with_securables(2 * INSERT_MAX_ROWS)
        )

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]

    # Should not have INSERT OVERWRITE of target (swap failed)
    overwrite_target = [
        s
        for s in statements
        if "INSERT OVERWRITE" in s and "main.state.securables" in s
    ]
    assert len(overwrite_target) == 0, "Swap should not occur when staging INSERT fails"

    # Should not have truncate on target
    target_truncates = [
        s for s in statements if s.strip() == "TRUNCATE TABLE main.state.securables"
    ]
    assert len(target_truncates) == 0, "Should not truncate target on staging failure"


def test_dumper_writer_drops_staging_after_failure(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state drops staging table even when staging INSERT fails."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: (
            sql.startswith("INSERT INTO main.state._tmp_securables ") and "'c50'" in sql
        ),
    )

    with pytest.raises(ExecutionBatchError):
        _dump(mock_workspace_client, tmp_path, _state_with_securables(100))

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    drops = [
        s
        for s in statements
        if s.strip() == "DROP TABLE IF EXISTS main.state._tmp_securables"
    ]
    assert len(drops) == 1, "Should drop staging table even on failure"


def test_dumper_writer_empty_table_still_swaps(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state swaps even an empty staging table into the target."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _mark_all_tables_as_existing(mock_workspace_client)  # All tables exist
    _dump(mock_workspace_client, tmp_path, _build_minimal_actual_state())

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]

    # Should have staging creates for all tables (even if no inserts)
    for spec in TABLE_SPECS:
        staging_name = f"main.state._tmp_{spec.name}"
        has_create = any(
            f"CREATE OR REPLACE TABLE {staging_name}" in s for s in statements
        )
        assert has_create, f"Should create staging for {spec.name} even if empty"

        # Should have swap statement (INSERT ... OVERWRITE ... BY NAME) for empty table
        target_name = f"main.state.{spec.name}"
        has_swap = any(
            "INSERT" in s.upper()
            and "OVERWRITE" in s.upper()
            and "BY NAME" in s.upper()
            and target_name in s
            for s in statements
        )
        assert has_swap, f"Should swap empty table {spec.name}"

        # Should drop staging
        has_drop = any(
            s.strip() == f"DROP TABLE IF EXISTS main.state._tmp_{spec.name}"
            for s in statements
        )
        assert has_drop, f"Should drop staging for {spec.name}"


def test_dumper_writer_reports_both_errors_when_evolution_and_recreate_fail(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """When the schema-evolution swap and the recreate fallback both fail, the table
    fails with both errors and its staging table is still dropped."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _existing_tables(
        mock_workspace_client, "securables"
    )  # Table exists, so evolution is attempted
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: "OVERWRITE main.state.securables " in sql,
        message="overwrite failed",
    )

    with pytest.raises(ExecutionBatchError) as exc_info:
        _dump(mock_workspace_client, tmp_path, _state_with_securables(1))

    assert str(exc_info.value).count("overwrite failed") >= 2
    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    assert "DROP TABLE IF EXISTS main.state._tmp_securables" in statements


def test_dumper_writer_swaps_after_all_inserts_and_drops_staging_last(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state creates the staging table, loads every batch into it, then swaps it
    into the target, and only then drops it."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _existing_tables(
        mock_workspace_client, "securables"
    )  # Table exists, so evolution is used
    _dump(mock_workspace_client, tmp_path, _state_with_securables(INSERT_MAX_ROWS * 2))

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    staging = "main.state._tmp_securables"
    create = next(
        i
        for i, s in enumerate(statements)
        if s.startswith(f"CREATE OR REPLACE TABLE {staging} ")
    )
    inserts = [
        i for i, s in enumerate(statements) if s.startswith(f"INSERT INTO {staging} ")
    ]
    swap = statements.index(
        _normalize_sql_backticks(
            build_overwrite_from_sql(
                "main.state.securables", staging, schema_evolution=True
            )
        )
    )
    drop = statements.index(f"DROP TABLE IF EXISTS {staging}")
    assert len(inserts) == 2
    assert create < min(inserts) and max(inserts) < swap < drop


def test_dumper_writer_warns_when_falling_back_to_recreate(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """dump_state logs a warning naming the table and the swap error when it falls
    back to recreating the table."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _existing_tables(
        mock_workspace_client, "securables"
    )  # Table exists, so evolution is attempted
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: "WITH SCHEMA EVOLUTION OVERWRITE main.state.securables " in sql,
        message="evolution unsupported",
    )

    with caplog.at_level(logging.WARNING):
        _dump(mock_workspace_client, tmp_path, _state_with_securables(1))

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "main.state.securables" in w and "evolution unsupported" in w for w in warnings
    )


def test_dumper_writer_falls_back_to_create_and_overwrite_when_evolution_insert_fails(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """When INSERT with schema evolution fails, dump_state falls back to CREATE OR REPLACE
    target + INSERT OVERWRITE without evolution; the swap succeeds and staging is dropped."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _existing_tables(
        mock_workspace_client, "securables"
    )  # Table exists, so evolution is attempted
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: "WITH SCHEMA EVOLUTION" in sql.upper(),
        message="schema evolution attempt failed",
    )

    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]

    # Find the failed evolution attempt and the fallback statements
    evolution_attempts = [
        s
        for s in statements
        if "INSERT" in s.upper()
        and "WITH SCHEMA EVOLUTION" in s.upper()
        and "OVERWRITE" in s.upper()
        and "main.state.securables" in s
    ]
    assert len(evolution_attempts) > 0, "Should attempt evolution"

    # Find fallback: CREATE OR REPLACE target followed by INSERT OVERWRITE without evolution
    target_creates = [
        s
        for s in statements
        if "CREATE OR REPLACE TABLE main.state.securables"
        in _normalize_sql_backticks(s)
        and "_tmp_" not in s
    ]
    assert len(target_creates) > 0, (
        "Should create target table as fallback after evolution fails"
    )

    fallback_inserts = [
        s
        for s in statements
        if "INSERT OVERWRITE" in s.upper()
        and "main.state.securables" in s
        and "WITH SCHEMA EVOLUTION" not in s.upper()
        and "BY NAME" in s.upper()
    ]
    assert len(fallback_inserts) > 0, (
        "Should have INSERT OVERWRITE without evolution as fallback"
    )

    # Verify order: CREATE comes before INSERT OVERWRITE
    last_create_idx = max(
        (
            i
            for i, s in enumerate(statements)
            if "CREATE OR REPLACE TABLE main.state.securables"
            in _normalize_sql_backticks(s)
        ),
        default=-1,
    )
    first_fallback_idx = min(
        (
            i
            for i, s in enumerate(statements)
            if "INSERT OVERWRITE" in s.upper()
            and "main.state.securables" in s
            and "WITH SCHEMA EVOLUTION" not in s.upper()
        ),
        default=float("inf"),
    )
    assert last_create_idx < first_fallback_idx, (
        "CREATE must come before fallback INSERT OVERWRITE"
    )

    # Staging should still be dropped
    drops = [
        s
        for s in statements
        if s.strip() == "DROP TABLE IF EXISTS main.state._tmp_securables"
    ]
    assert len(drops) == 1, "Should drop staging even after fallback"


def test_dumper_writer_reports_both_errors_when_drop_fails_after_failure(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """When staging INSERT fails AND DROP TABLE fails, ExecutionBatchError mentions both."""
    original = mock_workspace_client.statement_execution.execute_statement.side_effect

    def side_effect_with_drop_failure(*args, **kwargs):
        statement = kwargs.get("statement", args[0] if args else "")
        normalized = _normalize_sql_backticks(statement)
        # Fail staging INSERT
        if (
            "INSERT INTO main.state._tmp_securables" in normalized
            and "'c50'" in normalized
        ):
            mock_workspace_client.executed_sql.append(statement)
            raise RuntimeError("staging insert failed")
        # Also fail the DROP
        if normalized.strip() == "DROP TABLE IF EXISTS main.state._tmp_securables":
            mock_workspace_client.executed_sql.append(statement)
            raise RuntimeError("drop failed")
        return original(*args, **kwargs)

    mock_workspace_client.statement_execution.execute_statement.side_effect = (
        side_effect_with_drop_failure
    )

    with pytest.raises(ExecutionBatchError) as exc_info:
        _dump(mock_workspace_client, tmp_path, _state_with_securables(100))

    error_text = str(exc_info.value)
    # Error should mention both failures
    assert "staging insert failed" in error_text and "drop failed" in error_text, (
        f"Error should mention both insert and drop failures, got: {error_text}"
    )


def test_dumper_writer_table_fails_when_only_drop_fails(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """When only DROP TABLE fails (not the insert), ExecutionBatchError is raised."""
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: sql.strip().startswith("DROP TABLE IF EXISTS main.state._tmp_"),
        message="drop failed",
    )

    with pytest.raises(ExecutionBatchError) as exc_info:
        _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    error_text = str(exc_info.value)
    assert "drop failed" in error_text, (
        f"Error should mention drop failure, got: {error_text}"
    )


def test_dumper_writer_never_truncates(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state never executes TRUNCATE statements, even on failure."""
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: "INSERT INTO main.state._tmp_securables" in sql and "'c100'" in sql,
        message="insert failed",
    )

    with pytest.raises(ExecutionBatchError):
        _dump(mock_workspace_client, tmp_path, _state_with_securables(200))

    # Verify no TRUNCATE statements were executed
    assert not any("TRUNCATE" in s for s in mock_workspace_client.executed_sql), (
        "TRUNCATE should never be executed"
    )


# ---------------------------------------------------------------------------
# Progress logging
# ---------------------------------------------------------------------------


def _progress_lines(caplog: Any, table: str) -> list[str]:
    return [
        r.message
        for r in caplog.records
        if f"Writing to {table} (" in r.message
        and " of " in r.message
        and f"Writing to {table} (0 of " not in r.message
    ]


def test_dumper_writer_logs_progress_between_batches_of_a_long_table(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """Once the progress interval has elapsed, each completed batch logs the rows
    written so far out of the table's total; the final batch is covered by the
    'Wrote to' line instead."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _mark_all_tables_as_existing(mock_workspace_client)  # All tables exist
    state = _state_with_securables(2 * INSERT_MAX_ROWS + 500)
    with (
        patch("uc_abac.dumper.writer.fetch_actual_state", return_value=state),
        caplog.at_level(logging.INFO),
    ):
        dump_state(
            mock_workspace_client,
            config_dir=_build_minimal_config_dir(tmp_path),
            warehouse_id="warehouse-1",
            target_schema="main.state",
            max_parallel_tables=1,
            progress_interval_seconds=0,
        )

    lines = _progress_lines(caplog, "main.state.securables")
    assert [line.split("(")[-1] for line in lines] == [
        "1000 of 2500 rows)",
        "2000 of 2500 rows)",
    ]


def test_dumper_writer_logs_progress_while_later_batches_are_still_running(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """Progress is logged as batches complete, not only once the whole table is in:
    by the time the last batch runs, an earlier batch's progress line is out."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _mark_all_tables_as_existing(mock_workspace_client)  # All tables exist
    state = _state_with_securables(2 * INSERT_MAX_ROWS + 500)
    progress_seen_per_batch: list[int] = []
    original = mock_workspace_client.statement_execution.execute_statement.side_effect

    def _side_effect(*args, **kwargs):
        statement = _normalize_sql_backticks(kwargs.get("statement", ""))
        if statement.startswith("INSERT INTO main.state._tmp_securables "):
            progress_seen_per_batch.append(
                len(_progress_lines(caplog, "main.state.securables"))
            )
        return original(*args, **kwargs)

    mock_workspace_client.statement_execution.execute_statement.side_effect = (
        _side_effect
    )
    with (
        patch("uc_abac.dumper.writer.fetch_actual_state", return_value=state),
        caplog.at_level(logging.INFO),
    ):
        dump_state(
            mock_workspace_client,
            config_dir=_build_minimal_config_dir(tmp_path),
            warehouse_id="warehouse-1",
            target_schema="main.state",
            max_parallel_tables=1,
            progress_interval_seconds=0,
        )

    assert len(progress_seen_per_batch) == 3
    assert progress_seen_per_batch[-1] >= 1


def test_dumper_writer_logs_no_progress_for_a_table_written_within_the_interval(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _mark_all_tables_as_existing(mock_workspace_client)  # All tables exist
    state = _state_with_securables(2 * INSERT_MAX_ROWS + 500)
    with (
        patch("uc_abac.dumper.writer.fetch_actual_state", return_value=state),
        caplog.at_level(logging.INFO),
    ):
        dump_state(
            mock_workspace_client,
            config_dir=_build_minimal_config_dir(tmp_path),
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    assert _progress_lines(caplog, "main.state.securables") == []


# ---
# Dry-run logging assertions
# ---


def test_dumper_writer_dry_run_logs_no_writing_to_lines(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """dump_state with dry_run=True logs no 'Writing to' lines, but still logs 'Would write to'."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.side_effect = NotFound("schema not found")

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        with caplog.at_level(logging.INFO):
            dump_state(
                mock_workspace_client,
                config_dir=config_dir,
                warehouse_id="warehouse-1",
                target_schema="main.state",
                dry_run=True,
            )

    log_text = caplog.text
    # Should not contain "Writing to" lines
    for record in caplog.records:
        if "Writing to" in record.message:
            raise AssertionError(
                f"Expected no 'Writing to' lines in dry run, but found: {record.message}"
            )

    # Should still contain "Would write to" for at least one table
    assert any("Would write to" in record.message for record in caplog.records), (
        f"Expected 'Would write to' in dry run logs, got: {log_text}"
    )


# ---
# Schema comment tests
# ---


def test_dumper_writer_schema_missing_creates_schema_with_comment(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """dump_state creates schema with COMMENT when it doesn't exist."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.side_effect = NotFound("schema not found")

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _build_minimal_actual_state()

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
        )

    # Find CREATE SCHEMA statement
    create_schema_stmts = [
        sql
        for sql in mock_workspace_client.executed_sql
        if "CREATE SCHEMA" in sql.upper()
    ]
    assert len(create_schema_stmts) == 1, (
        f"Expected exactly one CREATE SCHEMA, got {len(create_schema_stmts)}: "
        f"{mock_workspace_client.executed_sql}"
    )

    schema_sql = create_schema_stmts[0]
    # Must contain COMMENT keyword
    assert "COMMENT" in schema_sql.upper(), (
        f"CREATE SCHEMA must contain COMMENT keyword: {schema_sql}"
    )

    assert TARGET_SCHEMA_COMMENT, "TARGET_SCHEMA_COMMENT must be non-empty"

    # Verify the SQL contains the escaped comment
    expected_comment = sql_string_literal(TARGET_SCHEMA_COMMENT)
    assert expected_comment in schema_sql, (
        f"CREATE SCHEMA must contain sql_string_literal(TARGET_SCHEMA_COMMENT):\n"
        f"  SQL: {schema_sql}\n"
        f"  Expected to contain: {expected_comment}"
    )


# ---
# Timezone handling tests
# ---


def test_dumper_writer_builds_context_with_run_date_for_timezone(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state computes run_date using run_date_for_timezone(timezone) and passes it to build_dump_context."""
    from uc_abac.utils import run_date_for_timezone

    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists

    captured_run_date = None

    def mock_build_dump_context(state, config, run_date):
        nonlocal captured_run_date
        captured_run_date = run_date
        # Return a MagicMock context to allow the test to proceed
        return MagicMock()

    with (
        patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch,
        patch("uc_abac.dumper.writer.build_dump_context") as mock_build_context,
    ):
        mock_fetch.return_value = _build_minimal_actual_state()
        mock_build_context.side_effect = mock_build_dump_context

        dump_state(
            mock_workspace_client,
            config_dir=config_dir,
            warehouse_id="warehouse-1",
            target_schema="main.state",
            timezone="Pacific/Kiritimati",
        )

    # Verify that build_dump_context was called with the run_date computed from the timezone
    expected_run_date = run_date_for_timezone("Pacific/Kiritimati")
    assert captured_run_date == expected_run_date, (
        f"Expected run_date to be {expected_run_date}, got {captured_run_date}"
    )


# ---------------------------------------------------------------------------
# Schema evolution and replace_tables flag tests
# ---------------------------------------------------------------------------


def test_dumper_writer_uses_schema_evolution_by_default(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state uses schema evolution in the swap statement by default."""
    _mark_all_tables_as_existing(mock_workspace_client)
    _dump(mock_workspace_client, tmp_path, _state_with_securables(10))

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    # Expected SQL format: INSERT WITH SCHEMA EVOLUTION OVERWRITE
    swap_with_evolution = [
        s
        for s in statements
        if "INSERT" in s.upper()
        and "WITH SCHEMA EVOLUTION" in s.upper()
        and "OVERWRITE" in s.upper()
        and "BY NAME" in s.upper()
    ]
    assert len(swap_with_evolution) > 0, (
        "Should use schema evolution in swap by default"
    )


def test_dumper_writer_replace_tables_flag_skips_schema_evolution(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state with replace_tables=True skips schema evolution."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _mark_all_tables_as_existing(
        mock_workspace_client
    )  # Tables exist but should be ignored
    with patch(
        "uc_abac.dumper.writer.fetch_actual_state",
        return_value=_state_with_securables(10),
    ):
        dump_state(
            mock_workspace_client,
            config_dir=_build_minimal_config_dir(tmp_path),
            warehouse_id="warehouse-1",
            target_schema="main.state",
            replace_tables=True,
            max_parallel_tables=1,
        )

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    # Should not have schema evolution in swap
    swap_with_evolution = [
        s
        for s in statements
        if "INSERT" in s.upper()
        and "WITH SCHEMA EVOLUTION" in s.upper()
        and "OVERWRITE" in s.upper()
    ]
    assert len(swap_with_evolution) == 0, (
        "Should not use schema evolution when replace_tables=True"
    )

    # Should still have swaps (just without schema evolution)
    swap_statements = [
        s
        for s in statements
        if "INSERT OVERWRITE" in s.upper() and "BY NAME" in s.upper()
    ]
    assert len(swap_statements) > 0, (
        "Should still have swap statements, just without schema evolution"
    )


def test_dumper_writer_replace_tables_uses_create_replace_for_swap(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state with replace_tables=True creates target and inserts without evolution."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _mark_all_tables_as_existing(
        mock_workspace_client
    )  # Tables exist but should be ignored
    with patch(
        "uc_abac.dumper.writer.fetch_actual_state",
        return_value=_state_with_securables(10),
    ):
        dump_state(
            mock_workspace_client,
            config_dir=_build_minimal_config_dir(tmp_path),
            warehouse_id="warehouse-1",
            target_schema="main.state",
            replace_tables=True,
            max_parallel_tables=1,
        )

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    # Should have INSERT OVERWRITE without schema evolution
    target_overwrites = [
        s
        for s in statements
        if "INSERT OVERWRITE main.state.securables" in s and "BY NAME" in s
    ]
    # At least one for securables
    assert len(target_overwrites) > 0, (
        "Should have INSERT OVERWRITE for target without schema evolution"
    )


# ---------------------------------------------------------------------------
# Dry run tests with staging behavior
# ---------------------------------------------------------------------------


def test_dumper_writer_dry_run_logs_staging_create(
    mock_workspace_client: MagicMock, tmp_path: Path, caplog: Any
) -> None:
    """dump_state with dry_run logs staging table creation at DEBUG level."""
    config_dir = _build_minimal_config_dir(tmp_path)
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    mock_workspace_client.tables.list.return_value = []  # No tables exist

    with patch("uc_abac.dumper.writer.fetch_actual_state") as mock_fetch:
        mock_fetch.return_value = _state_with_securables(10)

        with caplog.at_level(logging.DEBUG):
            dump_state(
                mock_workspace_client,
                config_dir=config_dir,
                warehouse_id="warehouse-1",
                target_schema="main.state",
                dry_run=True,
            )

    log_text = caplog.text
    # log_statement logs at DEBUG level, so check for staging table creation statements
    assert "_tmp_securables" in log_text, (
        f"Expected dry run to log staging table creation, got: {log_text}"
    )
    assert len(mock_workspace_client.executed_sql) == 0, "Dry run should execute no SQL"


# ---------------------------------------------------------------------------
# Concurrent batch execution tests
# ---------------------------------------------------------------------------


_STAGING_SECURABLES_INSERT = "INSERT INTO main.state._tmp_securables "


def _track_peak_in_flight(
    mock_workspace_client: MagicMock, predicate, *, seconds: float = 0.02
) -> list[int]:
    """Hold every statement matching ``predicate`` for ``seconds`` and track how many
    are in flight at once; returns a one-item list holding the peak."""
    original = mock_workspace_client.statement_execution.execute_statement.side_effect
    lock = threading.Lock()
    in_flight = [0]
    peak = [0]

    def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        if not predicate(_normalize_sql_backticks(kwargs.get("statement", ""))):
            return original(*args, **kwargs)
        with lock:
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        time.sleep(seconds)
        with lock:
            in_flight[0] -= 1
        return original(*args, **kwargs)

    mock_workspace_client.statement_execution.execute_statement.side_effect = (
        _side_effect
    )
    return peak


def test_dumper_writer_runs_a_tables_batches_concurrently(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state runs one table's INSERT batches concurrently, up to the limit."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    peak = _track_peak_in_flight(
        mock_workspace_client, lambda sql: sql.startswith(_STAGING_SECURABLES_INSERT)
    )

    _dump(
        mock_workspace_client,
        tmp_path,
        _state_with_securables(INSERT_MAX_ROWS * 6),
        max_parallel_tables=4,
    )

    assert 1 < peak[0] <= 4


def test_dumper_writer_caps_statements_in_flight_across_tables(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state never has more than max_parallel_tables statements in flight across
    every table and batch, and reaches that cap."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    peak = _track_peak_in_flight(mock_workspace_client, lambda sql: True)

    _dump(
        mock_workspace_client,
        tmp_path,
        _state_with_securables(INSERT_MAX_ROWS * 6),
        max_parallel_tables=2,
    )

    assert peak[0] == 2


def test_dumper_writer_runs_sequentially_with_one_worker(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state with max_parallel_tables=1 runs one statement at a time."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    peak = _track_peak_in_flight(mock_workspace_client, lambda sql: True, seconds=0.005)

    _dump(
        mock_workspace_client,
        tmp_path,
        _state_with_securables(INSERT_MAX_ROWS * 3),
        max_parallel_tables=1,
    )

    assert peak[0] == 1


def test_dumper_writer_executes_every_batch_when_parallel(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state executes every batch INSERT exactly once when batches run in
    parallel."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _dump(
        mock_workspace_client,
        tmp_path,
        _state_with_securables(INSERT_MAX_ROWS * 6),
        max_parallel_tables=4,
    )

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    inserts = [s for s in statements if s.startswith(_STAGING_SECURABLES_INSERT)]
    assert len(inserts) == 6
    assert len(set(inserts)) == 6


def test_dumper_writer_does_not_swap_when_a_parallel_batch_fails(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state fails a table whose parallel batch fails: the target is never
    touched and the staging table is still dropped."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: sql.startswith(_STAGING_SECURABLES_INSERT) and "'c1'" in sql,
        message="batch failed",
    )

    with pytest.raises(ExecutionBatchError, match="batch failed"):
        _dump(
            mock_workspace_client,
            tmp_path,
            _state_with_securables(INSERT_MAX_ROWS * 4),
            max_parallel_tables=4,
        )

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    assert not any("main.state.securables " in s for s in statements)
    assert "DROP TABLE IF EXISTS main.state._tmp_securables" in statements


def test_dumper_writer_skips_remaining_batches_after_a_batch_fails(
    mock_workspace_client: MagicMock, tmp_path: Path
) -> None:
    """dump_state stops submitting a table's batches once one has failed."""
    mock_workspace_client.schemas.get.return_value = MagicMock()  # Schema exists
    _fail_statements_matching(
        mock_workspace_client,
        lambda sql: sql.startswith(_STAGING_SECURABLES_INSERT),
        message="batch failed",
    )

    with pytest.raises(ExecutionBatchError):
        _dump(
            mock_workspace_client,
            tmp_path,
            _state_with_securables(INSERT_MAX_ROWS * 4),
            max_parallel_tables=1,
        )

    statements = [
        _normalize_sql_backticks(s) for s in mock_workspace_client.executed_sql
    ]
    assert len([s for s in statements if s.startswith(_STAGING_SECURABLES_INSERT)]) == 1
