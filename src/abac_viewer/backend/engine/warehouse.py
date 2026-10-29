"""Read the uc-abac dump tables through a SQL warehouse.

``WarehouseDumpReader`` is the production ``DumpReader``: it runs ``SELECT *`` against
each dump table in the target schema with the Statement Execution API (as the
``WorkspaceClient`` it is given, i.e. the app's service principal), waiting for the
statement and polling while it runs, and converts the JSON_ARRAY result to row dicts.
A statement still running after ``statement_timeout_seconds`` is canceled on the
warehouse and reported as a failure.
Results use the EXTERNAL_LINKS disposition so large tables are not bound by the inline
size limit; every chunk is followed via ``next_chunk_index``, and each presigned link is
downloaded without the workspace auth header.

Values are converted by the column's ``type_name`` in the result manifest: ``ARRAY``
columns (returned as JSON text) become tuples, ``BOOLEAN`` becomes ``bool``, integer
types become ``int``, and everything else stays a string; SQL NULL is ``None``.

Every failure — a malformed target schema name, a missing table, a failed, canceled or
timed-out statement, an API error — is raised as ``DumpReadError`` naming the table, so the app
can report it rather than crash.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    ColumnInfo,
    ColumnInfoTypeName,
    Disposition,
    ExecuteStatementRequestOnWaitTimeout,
    ExternalLink,
    ResultData,
    StatementResponse,
    StatementState,
)

from abac_viewer.backend.engine.dump import DumpReadError, DumpRow

_WAIT_TIMEOUT = "50s"
_DOWNLOAD_TIMEOUT_SECONDS = 60
# Errors from fetching or decoding one presigned link that are worth retrying: a
# dropped or cut-off connection (OSError covers URLError and timeouts), or a body
# truncated into invalid JSON.
_TRANSIENT_DOWNLOAD_ERRORS = (OSError, http.client.HTTPException, json.JSONDecodeError)
_PENDING_STATES = (StatementState.PENDING, StatementState.RUNNING)
_INTEGER_TYPES = frozenset(
    {
        ColumnInfoTypeName.BYTE,
        ColumnInfoTypeName.SHORT,
        ColumnInfoTypeName.INT,
        ColumnInfoTypeName.LONG,
    }
)
# A name part is either backtick-quoted (doubled backticks escape one) or bare.
_NAME_PART = r"`(?:[^`]|``)+`|[^.`]+"
_TARGET_SCHEMA = re.compile(rf"({_NAME_PART})\.({_NAME_PART})")


def _unquote_part(part: str) -> str:
    """Strip the backticks from a quoted name part and un-double its backticks."""
    if part.startswith("`"):
        return part[1:-1].replace("``", "`")
    return part


def _quote_identifier(name: str) -> str:
    """Backtick-quote one SQL identifier, doubling any embedded backtick."""
    return "`" + name.replace("`", "``") + "`"


def _select_statement(catalog: str, schema: str, table: str) -> str:
    """The ``SELECT *`` for one fully quoted dump table."""
    qualified = ".".join(_quote_identifier(part) for part in (catalog, schema, table))
    return f"SELECT * FROM {qualified}"


def parse_target_schema(target_schema: str) -> tuple[str, str]:
    """Split ``<catalog>.<schema>`` into its two parts; a part may be backtick-quoted
    (e.g. ``` `my-catalog`.state ```). Raises ``DumpReadError`` when it is not exactly
    two non-empty parts."""
    match = _TARGET_SCHEMA.fullmatch(target_schema)
    if match is None:
        raise DumpReadError(
            f"target schema {target_schema!r} must be <catalog>.<schema>"
        )
    catalog, schema = match.groups()
    return _unquote_part(catalog), _unquote_part(schema)


def _download(url: str) -> bytes:
    """GET one presigned result link with no auth header."""
    with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read()


def _cancel_quietly(client: WorkspaceClient, statement_id: str) -> None:
    """Ask the warehouse to cancel a statement, ignoring any error from the cancel."""
    with contextlib.suppress(Exception):
        client.statement_execution.cancel_execution(statement_id)


def _await_statement(
    client: WorkspaceClient,
    response: StatementResponse,
    table: str,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> StatementResponse:
    """Poll the statement until it leaves the PENDING and RUNNING states.

    The deadline is checked before each poll. Once it has passed while the statement is
    still pending, the statement is canceled on the warehouse (so it does not keep
    running unattended) and ``DumpReadError`` names ``table``.
    """
    deadline = time.monotonic() + timeout_seconds
    while response.status.state in _PENDING_STATES:
        if time.monotonic() >= deadline:
            _cancel_quietly(client, response.statement_id)
            raise DumpReadError(
                f"could not read {table}: timed out after {timeout_seconds:g} seconds"
            )
        time.sleep(poll_interval_seconds)
        response = client.statement_execution.get_statement(response.statement_id)
    return response


def _ensure_succeeded(response: StatementResponse, table: str) -> None:
    """Raise ``DumpReadError`` naming ``table`` unless the statement succeeded."""
    if response.status.state == StatementState.SUCCEEDED:
        return
    message = getattr(response.status.error, "message", None) or "no error message"
    raise DumpReadError(
        f"could not read {table}: statement {response.status.state.value}: {message}"
    )


def _columns(response: StatementResponse) -> list[ColumnInfo]:
    """The result's columns in position order, or none when there is no manifest."""
    if response.manifest is None or response.manifest.schema is None:
        return []
    return list(response.manifest.schema.columns or [])


def _all_links(
    client: WorkspaceClient, statement_id: str, result: ResultData | None
) -> list[ExternalLink]:
    """Every external link of the result, following ``next_chunk_index`` in order."""
    if result is None:
        return []
    links = list(result.external_links or [])
    next_index = result.next_chunk_index
    while next_index is not None:
        chunk = client.statement_execution.get_statement_result_chunk_n(
            statement_id, next_index
        )
        links = [*links, *(chunk.external_links or [])]
        next_index = chunk.next_chunk_index
    return links


def _convert(value: str | None, type_name: ColumnInfoTypeName | None) -> Any:
    """Convert one JSON_ARRAY cell by its column type; SQL NULL stays ``None``."""
    if value is None:
        return None
    if type_name == ColumnInfoTypeName.ARRAY:
        return tuple(json.loads(value))
    if type_name == ColumnInfoTypeName.BOOLEAN:
        return value == "true"
    if type_name in _INTEGER_TYPES:
        return int(value)
    return value


def _decode_row(columns: Sequence[ColumnInfo], values: Sequence[str | None]) -> DumpRow:
    """One result row as a dict keyed by column name."""
    return {
        column.name: _convert(value, column.type_name)
        for column, value in zip(columns, values, strict=True)
    }


def _is_client_error(error: Exception) -> bool:
    """Whether ``error`` is an HTTP 4xx response, e.g. an expired presigned link (403),
    which the same URL cannot recover from."""
    return isinstance(error, urllib.error.HTTPError) and 400 <= error.code < 500


def _fetch_values(
    url: str, download: Callable[[str], bytes], attempts: int, delay_seconds: float
) -> list[list[str | None]]:
    """Download and decode one link's JSON_ARRAY body, retrying transient failures up
    to ``attempts`` times in total (presigned downloads are occasionally cut off). An
    HTTP 4xx response is not transient and is raised at once."""
    for attempt in range(1, attempts + 1):
        try:
            return json.loads(download(url))
        except _TRANSIENT_DOWNLOAD_ERRORS as error:
            if attempt == attempts or _is_client_error(error):
                raise
            time.sleep(delay_seconds * attempt)
    return []


def _rows_from_links(
    columns: Sequence[ColumnInfo],
    links: Sequence[ExternalLink],
    fetch: Callable[[str], list[list[str | None]]],
) -> list[DumpRow]:
    """Fetch each link's rows and decode them, in link order."""
    return [
        _decode_row(columns, values)
        for link in links
        for values in fetch(link.external_link)
    ]


class WarehouseDumpReader:
    """A ``DumpReader`` over the dump tables in ``target_schema``."""

    def __init__(
        self,
        client: WorkspaceClient,
        warehouse_id: str,
        target_schema: str,
        *,
        poll_interval_seconds: float = 2.0,
        statement_timeout_seconds: float = 600.0,
        download: Callable[[str], bytes] | None = None,
        download_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
    ):
        """``statement_timeout_seconds`` bounds how long one table's statement may stay
        pending or running before it is canceled and the read fails. ``download``
        fetches one presigned result link's body; it defaults to a plain HTTPS GET (no
        auth header) and exists so tests need no network. A failed or truncated
        download is retried up to ``download_attempts`` times in total."""
        self._client = client
        self._warehouse_id = warehouse_id
        self._target_schema = target_schema
        self._poll_interval_seconds = poll_interval_seconds
        self._statement_timeout_seconds = statement_timeout_seconds
        self._download = download or _download
        self._download_attempts = download_attempts
        self._retry_delay_seconds = retry_delay_seconds

    @property
    def source(self) -> str:
        """The target schema, as given."""
        return self._target_schema

    def _fetch(self, url: str) -> list[list[str | None]]:
        return _fetch_values(
            url, self._download, self._download_attempts, self._retry_delay_seconds
        )

    def _read_rows(self, table: str) -> list[DumpRow]:
        """Run the table's SELECT on the warehouse and decode every chunk."""
        catalog, schema = parse_target_schema(self._target_schema)
        response = self._client.statement_execution.execute_statement(
            statement=_select_statement(catalog, schema, table),
            warehouse_id=self._warehouse_id,
            disposition=Disposition.EXTERNAL_LINKS,
            wait_timeout=_WAIT_TIMEOUT,
            on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
        )
        response = _await_statement(
            self._client,
            response,
            table,
            self._poll_interval_seconds,
            self._statement_timeout_seconds,
        )
        _ensure_succeeded(response, table)
        links = _all_links(self._client, response.statement_id, response.result)
        return _rows_from_links(_columns(response), links, self._fetch)

    def read(self, table: str) -> Sequence[DumpRow]:
        """All rows of ``<target_schema>.<table>``, quoted as SQL identifiers."""
        try:
            return self._read_rows(table)
        except DumpReadError:
            raise
        except Exception as error:
            raise DumpReadError(f"could not read {table}: {error}") from error
