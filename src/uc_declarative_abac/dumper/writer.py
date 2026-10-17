"""``dump_state``: fetch the actual state behind a config and write it to tables."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _ExecutionContext:
    """What a worker needs to run statements.

    ``budget`` is the run's shared statement budget: one semaphore, sized to
    ``max_parallel_tables``, that every statement of every table holds while it
    executes, so the total in flight never exceeds that cap however many tables and
    batches are being written at once.
    """

    uc_helper: UnityCatalogHelper
    logger: DumpLogger
    dry_run: bool
    budget: threading.BoundedSemaphore


def _ensure_target_schema(
    workspace_client: WorkspaceClient,
    uc_helper: UnityCatalogHelper,
    target_schema: str,
    logger: DumpLogger,
    dry_run: bool,
) -> bool:
    """Create the target schema only when it is missing; return whether it existed.

    Runs before the (slow) state fetch so a missing catalog or a permission problem
    fails fast. A missing schema gets a ``CREATE SCHEMA`` with a comment; an existing
    schema gets no DDL at all (its comment is never overwritten). The existence check
    is read-only, so it also runs in a dry run. Returns False when the schema was
    missing (so it has no tables to list; see ``_existing_table_names``).
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
        return False
    except Exception as exc:
        logger.log_error(
            ExecutionError(context=f"target schema {target_schema}", exception=exc)
        )
        raise
    logger.log_target_schema_exists(target_schema)
    return True


def _existing_table_names(
    workspace_client: WorkspaceClient, target_schema: str, schema_existed: bool
) -> frozenset[str]:
    """The lower-cased names of the tables already in the target schema.

    One read-only listing up front, so a table known to be missing (e.g. on the first
    run) is created directly rather than through a schema-evolution swap that is
    certain to fail and warn. A schema created by this run has no tables, so it isn't
    listed. Names are lower-cased because Unity Catalog stores them that way.
    """
    if not schema_existed:
        return frozenset()
    catalog, schema = target_schema.split(".", 1)
    tables = workspace_client.tables.list(
        catalog_name=catalog,
        schema_name=schema,
        omit_columns=True,
        omit_properties=True,
        omit_username=True,
    )
    return frozenset(table.name.lower() for table in tables)


def _execute(statement: str, ctx: _ExecutionContext) -> None:
    """Log and run one statement, holding the shared budget only while it executes.

    The budget is never held while waiting on other work (e.g. a table waiting on its
    batches), so the nested table/batch fan-out can't deadlock.
    """
    ctx.logger.log_statement(statement)
    if ctx.dry_run:
        return
    with ctx.budget:
        ctx.uc_helper.execute_sql(statement)


def _drop_staging(
    staging_full_name: str,
    failure: Exception | None,
    *,
    ctx: _ExecutionContext,
) -> None:
    """Drop a table's staging table after its load, successful or not.

    A drop failure after an earlier ``failure`` is raised together with it so neither
    is lost; a drop failure on its own fails the table.
    """
    statement = f"DROP TABLE IF EXISTS {quote_securable(staging_full_name)}"
    try:
        _execute(statement, ctx)
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
    ctx: _ExecutionContext,
) -> None:
    """Recreate the target from the spec, then load it from the staging table.

    Not atomic: the target is empty between the two statements.
    """
    _execute(build_create_table_sql(target_full_name, spec), ctx)
    _execute(
        build_overwrite_from_sql(
            target_full_name, staging_full_name, schema_evolution=False
        ),
        ctx,
    )


def _swap_into_target(
    target_full_name: str,
    staging_full_name: str,
    spec: TableSpec,
    *,
    replace_tables: bool,
    target_exists: bool,
    ctx: _ExecutionContext,
) -> None:
    """Move the staging table's rows into the target.

    A target that doesn't exist yet is created and loaded directly (see
    ``_replace_target``), as is every target with ``replace_tables``. For an existing
    target, a single ``INSERT WITH SCHEMA EVOLUTION OVERWRITE ... BY
    NAME`` swaps the rows in atomically, so readers keep the previous snapshot until it
    commits; columns new to the target are appended at its end. If that fails for any
    reason (e.g. a column's type changed incompatibly), a warning is logged and the
    target is recreated instead (``_replace_target``). If both paths fail, both errors
    are raised together. A recreate is not atomic: if its load fails, the target is
    left empty.
    """
    replace = partial(
        _replace_target,
        target_full_name,
        staging_full_name,
        spec,
        ctx=ctx,
    )
    if replace_tables or not target_exists:
        replace()
        return
    evolution_sql = build_overwrite_from_sql(
        target_full_name, staging_full_name, schema_evolution=True
    )
    try:
        _execute(evolution_sql, ctx)
    except Exception as evolution_exc:  # noqa: BLE001 — any failure falls back to a recreate
        ctx.logger.log_table_recreating(target_full_name, evolution_exc)
        try:
            replace()
        except Exception as replace_exc:
            raise RuntimeError(
                f"{evolution_exc}; recreating the table also failed: {replace_exc}"
            ) from replace_exc


def _execute_batch(
    indexed_batch: tuple[int, InsertBatch],
    *,
    table_full_name: str,
    batch_count: int,
    failed: threading.Event,
    ctx: _ExecutionContext,
) -> int:
    """Run one INSERT batch; skipped (0 rows) once another batch of the table failed."""
    index, batch = indexed_batch
    if failed.is_set():
        return 0
    ctx.logger.log_batch(
        table_full_name,
        index,
        batch_count,
        batch.row_count,
        len(batch.sql.encode("utf-8")),
    )
    _execute(batch.sql, ctx)
    return batch.row_count


def _raise_batch_errors(errors: list[Exception]) -> None:
    """Raise the first batch failure, noting how many others failed too."""
    if not errors:
        return
    first = errors[0]
    if len(errors) == 1:
        raise first
    raise RuntimeError(
        f"{first}; {len(errors) - 1} more batch(es) also failed"
    ) from first


def _insert_batches(
    table_full_name: str,
    batches: list[InsertBatch],
    *,
    ctx: _ExecutionContext,
    progress_interval_seconds: float,
    max_parallel_tables: int,
) -> None:
    """Run a table's INSERT batches concurrently, logging progress for long writes.

    The batches go into the table's staging table, up to ``max_parallel_tables`` at a
    time and further limited by the run's shared statement budget (see
    ``_ExecutionContext``). Concurrent ``INSERT INTO`` statements are blind appends,
    which don't conflict in Delta. Once a batch fails, batches not yet started are
    skipped, and the table fails when those in flight finish.

    As each batch completes, if ``progress_interval_seconds`` have passed since the
    table's last log line, the rows written so far are logged. Progress is only known
    at batch boundaries, and no line is logged once every row is in (the table's
    "Wrote to" line follows). ``on_complete`` runs on this (the table's) thread, so
    the progress counters need no lock.
    """
    row_count = sum(batch.row_count for batch in batches)
    rows_written = 0
    last_logged = time.monotonic()
    errors: list[Exception] = []
    failed = threading.Event()

    def _on_complete(
        _batch: tuple[int, InsertBatch], written: int | None, error: Exception | None
    ) -> None:
        nonlocal rows_written, last_logged
        if error is not None:
            errors.append(error)
            failed.set()
            return
        rows_written += written or 0
        now = time.monotonic()
        if rows_written < row_count and now - last_logged >= progress_interval_seconds:
            ctx.logger.log_table_progress(table_full_name, rows_written, row_count)
            last_logged = now

    parallel_for_each(
        list(enumerate(batches, start=1)),
        partial(
            _execute_batch,
            table_full_name=table_full_name,
            batch_count=len(batches),
            failed=failed,
            ctx=ctx,
        ),
        max_workers=max_parallel_tables,
        on_complete=_on_complete,
    )
    _raise_batch_errors(errors)


def _load_and_swap(
    target_full_name: str,
    staging_full_name: str,
    spec: TableSpec,
    batches: list[InsertBatch],
    replace_tables: bool,
    target_exists: bool,
    *,
    ctx: _ExecutionContext,
    progress_interval_seconds: float,
    max_parallel_tables: int,
) -> None:
    """Create the staging table, load every batch into it, then swap into the target."""
    _execute(build_create_table_sql(staging_full_name, spec), ctx)
    _insert_batches(
        target_full_name,
        batches,
        ctx=ctx,
        progress_interval_seconds=progress_interval_seconds,
        max_parallel_tables=max_parallel_tables,
    )
    _swap_into_target(
        target_full_name,
        staging_full_name,
        spec,
        replace_tables=replace_tables,
        target_exists=target_exists,
        ctx=ctx,
    )


def _write_table(
    spec: TableSpec,
    *,
    target_schema: str,
    state: ActualState,
    context: DumpContext,
    logger: DumpLogger,
    uc_helper: UnityCatalogHelper,
    dry_run: bool,
    progress_interval_seconds: float,
    replace_tables: bool,
    budget: threading.BoundedSemaphore,
    max_parallel_tables: int,
    existing_tables: frozenset[str],
) -> tuple[int, int]:
    """Load one table via its staging table; returns ``(row_count, batch_count)``.

    Runs on a worker thread. Rows are loaded into ``_tmp_<table>`` (see
    ``staging_table_name``) and only then swapped into the target (see
    ``_swap_into_target``), so a failed staging load leaves the target's previous
    snapshot in place. Progress is logged against the target's name. The staging table
    is dropped whether or not the load succeeded. ``existing_tables`` holds the
    target schema's table names (see ``_existing_table_names``).
    """
    table_full_name = f"{target_schema}.{spec.name}"
    staging_full_name = staging_table_name(table_full_name)
    target_exists = spec.name.lower() in existing_tables
    rows = spec.rows(state, context)
    logger.log_table_started(table_full_name, len(rows))
    batches = build_insert_batches(staging_full_name, spec, rows)
    ctx = _ExecutionContext(
        uc_helper=uc_helper,
        logger=logger,
        dry_run=dry_run,
        budget=budget,
    )
    drop = partial(
        _drop_staging,
        staging_full_name,
        ctx=ctx,
    )
    try:
        _load_and_swap(
            table_full_name,
            staging_full_name,
            spec,
            batches,
            replace_tables,
            target_exists,
            ctx=ctx,
            progress_interval_seconds=progress_interval_seconds,
            max_parallel_tables=max_parallel_tables,
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

    Each table in ``TABLE_SPECS`` has its rows fully replaced: rows are loaded into a
    staging table and then swapped in (see ``_write_table``), so a table whose load
    fails keeps its previous snapshot; a table that doesn't exist yet is created.
    ``replace_tables`` recreates each table from its spec instead of swapping in place
    (see ``_swap_into_target``). Tables, and the insert batches within each table, are
    written concurrently, with at most ``max_parallel_tables`` SQL statements in flight
    in total (see ``_ExecutionContext``). A failed table doesn't stop the others; all
    failures are raised together as ``ExecutionBatchError`` at the end.
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
    schema_existed = _ensure_target_schema(
        workspace_client, uc_helper, target_schema, logger, dry_run
    )

    logger.log_fetching_state()
    state = fetch_actual_state(config, uc_helper, ws_helper)
    logger.log_fetched_state(state)
    context = build_dump_context(state, config, run_date_for_timezone(timezone))

    existing_tables = _existing_table_names(
        workspace_client, target_schema, schema_existed
    )

    budget = threading.BoundedSemaphore(max(1, max_parallel_tables))

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
            logger=logger,
            uc_helper=uc_helper,
            dry_run=dry_run,
            progress_interval_seconds=progress_interval_seconds,
            replace_tables=replace_tables,
            budget=budget,
            max_parallel_tables=max_parallel_tables,
            existing_tables=existing_tables,
        ),
        max_workers=max_parallel_tables,
        on_complete=_on_complete,
    )
    logger.log_summary(_table_full_names(target_schema))
    if logger.errors:
        raise ExecutionBatchError(logger.errors)
