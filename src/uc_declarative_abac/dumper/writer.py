"""``dump_state``: fetch the actual state behind a config and write it to tables."""

from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import Literal

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

from uc_declarative_abac.dumper.logger import DumpLogger
from uc_declarative_abac.dumper.sql import (
    InsertBatch,
    build_create_table_sql,
    build_insert_batches,
    build_overwrite_from_sql,
    staging_table_name,
)
from uc_declarative_abac.dumper.tables import (
    TABLE_SPECS,
    TARGET_SCHEMA_COMMENT,
    DumpContext,
    TableSpec,
    build_dump_context,
)
from uc_declarative_abac.helpers import UnityCatalogHelper, WorkspaceHelper
from uc_declarative_abac.orchestrator import (
    ActualState,
    fetch_actual_state,
    load_config,
)
from uc_declarative_abac.utils import (
    ExecutionBatchError,
    ExecutionError,
    parallel_for_each,
    quote_securable,
    run_date_for_timezone,
    sql_string_literal,
)

DEFAULT_MAX_PARALLEL_TABLES = 8
DEFAULT_PROGRESS_INTERVAL_SECONDS = 10.0


def _ensure_target_schema(
    workspace_client: WorkspaceClient,
    uc_helper: UnityCatalogHelper,
    target_schema: str,
    logger: DumpLogger,
    dry_run: bool,
) -> None:
    """Create the target schema only when it is missing.

    Runs before the (slow) state fetch so a missing catalog or a permission problem
    fails fast. A missing schema gets a ``CREATE SCHEMA`` with a comment; an existing
    schema gets no DDL at all (its comment is never overwritten). The existence check
    is read-only, so it also runs in a dry run.
    """
    try:
        workspace_client.schemas.get(target_schema)
    except NotFound:
        if not dry_run:
            uc_helper.execute_sql(
                f"CREATE SCHEMA {quote_securable(target_schema)} "
                f"COMMENT {sql_string_literal(TARGET_SCHEMA_COMMENT)}"
            )
        logger.log_target_schema_created(target_schema)
        return
    except Exception as exc:
        logger.log_error(
            ExecutionError(context=f"target schema {target_schema}", exception=exc)
        )
        raise
    logger.log_target_schema_exists(target_schema)


def _execute(
    statement: str, uc_helper: UnityCatalogHelper, logger: DumpLogger, dry_run: bool
) -> None:
    logger.log_statement(statement)
    if not dry_run:
        uc_helper.execute_sql(statement)


def _drop_staging(
    staging_full_name: str,
    failure: Exception | None,
    *,
    uc_helper: UnityCatalogHelper,
    logger: DumpLogger,
    dry_run: bool,
) -> None:
    """Drop a table's staging table after its load, successful or not.

    A drop failure after an earlier ``failure`` is raised together with it so neither
    is lost; a drop failure on its own fails the table.
    """
    statement = f"DROP TABLE IF EXISTS {quote_securable(staging_full_name)}"
    logger.log_statement(statement)
    try:
        if not dry_run:
            uc_helper.execute_sql(statement)
    except Exception as drop_exc:
        if failure is not None:
            raise RuntimeError(
                f"{failure}; dropping the staging table {staging_full_name} also "
                f"failed: {drop_exc}"
            ) from failure
        raise


def _replace_target(
    target_full_name: str,
    staging_full_name: str,
    spec: TableSpec,
    *,
    uc_helper: UnityCatalogHelper,
    logger: DumpLogger,
    dry_run: bool,
) -> None:
    """Recreate the target from the spec, then load it from the staging table.

    Not atomic: the target is empty between the two statements.
    """
    _execute(build_create_table_sql(target_full_name, spec), uc_helper, logger, dry_run)
    _execute(
        build_overwrite_from_sql(
            target_full_name, staging_full_name, schema_evolution=False
        ),
        uc_helper,
        logger,
        dry_run,
    )


def _swap_into_target(
    target_full_name: str,
    staging_full_name: str,
    spec: TableSpec,
    *,
    replace_tables: bool,
    uc_helper: UnityCatalogHelper,
    logger: DumpLogger,
    dry_run: bool,
) -> None:
    """Move the staging table's rows into the target.

    By default a single ``INSERT WITH SCHEMA EVOLUTION OVERWRITE ... BY NAME`` swaps
    the rows in atomically, so readers keep the previous snapshot until it commits;
    columns new to an existing target are appended at its end. If that fails for any
    reason (e.g. the target doesn't exist yet, or a column's type changed
    incompatibly), a warning
    is logged and the target is recreated instead (``_replace_target``).
    ``replace_tables`` skips straight to the recreate. If both paths fail, both errors
    are raised together. A recreate is not atomic: if its load fails, the target is
    left empty.
    """
    replace = partial(
        _replace_target,
        target_full_name,
        staging_full_name,
        spec,
        uc_helper=uc_helper,
        logger=logger,
        dry_run=dry_run,
    )
    if replace_tables:
        replace()
        return
    evolution_sql = build_overwrite_from_sql(
        target_full_name, staging_full_name, schema_evolution=True
    )
    try:
        _execute(evolution_sql, uc_helper, logger, dry_run)
    except Exception as evolution_exc:  # noqa: BLE001 — any failure falls back to a recreate
        logger.log_table_recreating(target_full_name, evolution_exc)
        try:
            replace()
        except Exception as replace_exc:
            raise RuntimeError(
                f"{evolution_exc}; recreating the table also failed: {replace_exc}"
            ) from replace_exc


def _insert_batches(
    table_full_name: str,
    batches: list[InsertBatch],
    *,
    uc_helper: UnityCatalogHelper,
    logger: DumpLogger,
    dry_run: bool,
    progress_interval_seconds: float,
) -> None:
    """Run a table's INSERT batches in order, logging progress for long writes.

    After each batch, if ``progress_interval_seconds`` have passed since the table's
    last log line, the rows written so far are logged. Progress is only known at
    batch boundaries, and no line is logged once every row is in (the table's
    "Wrote to" line follows).
    """
    row_count = sum(batch.row_count for batch in batches)
    rows_written = 0
    last_logged = time.monotonic()
    for index, batch in enumerate(batches, start=1):
        logger.log_batch(
            table_full_name,
            index,
            len(batches),
            batch.row_count,
            len(batch.sql.encode("utf-8")),
        )
        _execute(batch.sql, uc_helper, logger, dry_run)
        rows_written += batch.row_count
        now = time.monotonic()
        if rows_written < row_count and now - last_logged >= progress_interval_seconds:
            logger.log_table_progress(table_full_name, rows_written, row_count)
            last_logged = now


def _load_and_swap(
    target_full_name: str,
    staging_full_name: str,
    spec: TableSpec,
    batches: list[InsertBatch],
    replace_tables: bool,
    *,
    uc_helper: UnityCatalogHelper,
    logger: DumpLogger,
    dry_run: bool,
    progress_interval_seconds: float,
) -> None:
    """Create the staging table, load every batch into it, then swap into the target."""
    _execute(
        build_create_table_sql(staging_full_name, spec),
        uc_helper,
        logger,
        dry_run,
    )
    _insert_batches(
        target_full_name,
        batches,
        uc_helper=uc_helper,
        logger=logger,
        dry_run=dry_run,
        progress_interval_seconds=progress_interval_seconds,
    )
    _swap_into_target(
        target_full_name,
        staging_full_name,
        spec,
        replace_tables=replace_tables,
        uc_helper=uc_helper,
        logger=logger,
        dry_run=dry_run,
    )


def _write_table(
    spec: TableSpec,
    *,
    target_schema: str,
    state: ActualState,
    context: DumpContext,
    uc_helper: UnityCatalogHelper,
    logger: DumpLogger,
    dry_run: bool,
    progress_interval_seconds: float,
    replace_tables: bool,
) -> tuple[int, int]:
    """Load one table via its staging table; returns ``(row_count, batch_count)``.

    Runs on a worker thread. Rows are loaded into ``_tmp_<table>`` (see
    ``staging_table_name``) and only then swapped into the target (see
    ``_swap_into_target``), so a failed staging load leaves the target's previous
    snapshot in place. Progress is logged against the target's name. The staging table is dropped whether or not the load succeeded.
    """
    table_full_name = f"{target_schema}.{spec.name}"
    staging_full_name = staging_table_name(table_full_name)
    rows = spec.rows(state, context)
    logger.log_table_started(table_full_name, len(rows))
    batches = build_insert_batches(staging_full_name, spec, rows)
    drop = partial(
        _drop_staging,
        staging_full_name,
        uc_helper=uc_helper,
        logger=logger,
        dry_run=dry_run,
    )
    try:
        _load_and_swap(
            table_full_name,
            staging_full_name,
            spec,
            batches,
            replace_tables,
            uc_helper=uc_helper,
            logger=logger,
            dry_run=dry_run,
            progress_interval_seconds=progress_interval_seconds,
        )
    except Exception as exc:
        drop(exc)
        raise
    drop(None)
    return (len(rows), len(batches))


def _table_full_names(target_schema: str) -> list[str]:
    return [f"{target_schema}.{spec.name}" for spec in TABLE_SPECS]


def dump_state(
    workspace_client: WorkspaceClient,
    *,
    config_dir: Path,
    warehouse_id: str,
    target_schema: str,
    system_catalog: str = "system",
    ref_override_strategy: Literal["merge", "replace"] = "merge",
    max_parallel_tables: int = DEFAULT_MAX_PARALLEL_TABLES,
    dry_run: bool = False,
    progress_interval_seconds: float = DEFAULT_PROGRESS_INTERVAL_SECONDS,
    timezone: str = "UTC",
    replace_tables: bool = False,
) -> None:
    """Fetch the actual state behind the config and write it to the target schema.

    Each table in ``TABLE_SPECS`` has its rows fully replaced, up to
    ``max_parallel_tables`` at a time: rows are loaded into a staging table and then
    swapped in (see ``_write_table``), so a table whose load fails keeps its previous
    snapshot. ``replace_tables`` recreates each table from its spec instead of
    swapping in place (see ``_swap_into_target``). A failed table doesn't stop the
    others; all failures are raised together as ``ExecutionBatchError`` at the end.
    ``dry_run`` builds and logs every statement but executes none.
    A table still loading after ``progress_interval_seconds`` logs its rows written
    so far (at most once per interval).

    The ``WorkspaceHelper`` is built with ``manage_groups`` and
    ``manage_domain_owners`` set even when the config declares no groups: the full
    fetch needs the group and domain-owner id maps to read memberships, assumers, and
    domain owners (see ``fetch_actual_state``).
    """
    logger = DumpLogger(dry_run=dry_run)
    logger.log_banner()
    config = load_config(config_dir, ref_override_strategy)
    uc_helper = UnityCatalogHelper(
        workspace_client, warehouse_id, system_catalog=system_catalog
    )
    ws_helper = WorkspaceHelper(
        workspace_client, manage_groups=True, manage_domain_owners=True
    )
    _ensure_target_schema(workspace_client, uc_helper, target_schema, logger, dry_run)

    logger.log_fetching_state()
    state = fetch_actual_state(config, uc_helper, ws_helper)
    logger.log_fetched_state(state)
    context = build_dump_context(state, config, run_date_for_timezone(timezone))

    def _on_complete(
        spec: TableSpec, result: tuple[int, int] | None, error: Exception | None
    ) -> None:
        table_full_name = f"{target_schema}.{spec.name}"
        if error is not None:
            logger.log_table_failed(table_full_name, error)
        elif result is not None:
            logger.log_table_written(table_full_name, *result)

    logger.log_section_header("Tables")
    parallel_for_each(
        list(TABLE_SPECS),
        partial(
            _write_table,
            target_schema=target_schema,
            state=state,
            context=context,
            uc_helper=uc_helper,
            logger=logger,
            dry_run=dry_run,
            progress_interval_seconds=progress_interval_seconds,
            replace_tables=replace_tables,
        ),
        max_workers=max_parallel_tables,
        on_complete=_on_complete,
    )
    logger.log_summary(_table_full_names(target_schema))
    if logger.errors:
        raise ExecutionBatchError(logger.errors)
