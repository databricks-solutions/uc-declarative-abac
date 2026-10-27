from __future__ import annotations

import http.client
import json
import urllib.error
from collections.abc import Callable, Sequence

import pytest
from databricks.sdk.errors import NotFound
from databricks.sdk.service.sql import (
    ColumnInfo,
    ColumnInfoTypeName,
    ExternalLink,
    Format,
    ResultData,
    ResultManifest,
    ResultSchema,
    ServiceError,
    StatementResponse,
    StatementState,
    StatementStatus,
)

from abac_viewer.backend.engine.dump import DumpReadError
from abac_viewer.backend.engine.warehouse import (
    WarehouseDumpReader,
    parse_target_schema,
)

WAREHOUSE_ID = "wh-1"
TARGET = "cat.schema"
STATEMENT_ID = "stmt-1"


# --- test doubles


def _next_scripted(queue: list):
    if not queue:
        raise AssertionError("client called more times than the test scripted")
    item = queue.pop(0)
    if isinstance(item, BaseException):
        raise item
    return item


class FakeStatementExecution:
    """Scripted stand-in for ``WorkspaceClient.statement_execution``.

    Each queue is consumed in order; an exception queued in place of a response is raised.
    Every SQL statement and chunk request is recorded for assertions.
    """

    def __init__(
        self,
        *,
        execute: Sequence = (),
        polls: Sequence = (),
        default_poll: StatementResponse | None = None,
        chunks: dict[int, ResultData] | None = None,
    ):
        self._execute = list(execute)
        self._polls = list(polls)
        self._default_poll = default_poll
        self._chunks = dict(chunks or {})
        self.executed: list[dict] = []
        self.polled_statement_ids: list[str] = []
        self.canceled_statement_ids: list[str] = []
        self.chunk_requests: list[tuple[str, int]] = []

    def execute_statement(self, **kwargs):
        self.executed.append(kwargs)
        return _next_scripted(self._execute)

    def get_statement(self, statement_id: str):
        self.polled_statement_ids.append(statement_id)
        if not self._polls and self._default_poll is not None:
            return self._default_poll
        return _next_scripted(self._polls)

    def cancel_execution(self, statement_id: str):
        self.canceled_statement_ids.append(statement_id)

    def get_statement_result_chunk_n(self, statement_id: str, chunk_index: int):
        self.chunk_requests.append((statement_id, chunk_index))
        return self._chunks[chunk_index]


class FakeWorkspaceClient:
    def __init__(self, statement_execution: FakeStatementExecution):
        self.statement_execution = statement_execution


def _downloader(bodies: dict[str, list[list[str | None]]]) -> Callable[[str], bytes]:
    encoded = {url: json.dumps(rows).encode() for url, rows in bodies.items()}
    return lambda url: encoded[url]


def _no_download(url: str) -> bytes:
    raise AssertionError(f"unexpected download of {url}")


# --- response builders


def _status(state: StatementState, *, message: str | None = None) -> StatementStatus:
    error = ServiceError(message=message) if message else None
    return StatementStatus(state=state, error=error)


def _status_only(
    state: StatementState, *, message: str | None = None
) -> StatementResponse:
    return StatementResponse(
        statement_id=STATEMENT_ID, status=_status(state, message=message)
    )


def _manifest(columns: Sequence[tuple[str, ColumnInfoTypeName]]) -> ResultManifest:
    return ResultManifest(
        format=Format.JSON_ARRAY,
        schema=ResultSchema(
            column_count=len(columns),
            columns=[
                ColumnInfo(name=name, position=position, type_name=type_name)
                for position, (name, type_name) in enumerate(columns)
            ],
        ),
    )


def _link(
    url: str, *, chunk_index: int = 0, next_chunk_index: int | None = None
) -> ExternalLink:
    return ExternalLink(
        external_link=url,
        chunk_index=chunk_index,
        next_chunk_index=next_chunk_index,
    )


def _succeeded(
    columns: Sequence[tuple[str, ColumnInfoTypeName]],
    links: Sequence[ExternalLink],
    *,
    next_chunk_index: int | None = None,
) -> StatementResponse:
    return StatementResponse(
        statement_id=STATEMENT_ID,
        status=_status(StatementState.SUCCEEDED),
        manifest=_manifest(columns),
        result=ResultData(
            chunk_index=0,
            external_links=list(links),
            next_chunk_index=next_chunk_index,
        ),
    )


def _reader(
    client: FakeWorkspaceClient, *, download=None, statement_timeout_seconds=60.0
) -> WarehouseDumpReader:
    return WarehouseDumpReader(
        client,
        WAREHOUSE_ID,
        TARGET,
        poll_interval_seconds=0,
        statement_timeout_seconds=statement_timeout_seconds,
        download=download or _no_download,
    )


def _read_one_chunk(
    columns: Sequence[tuple[str, ColumnInfoTypeName]],
    body_rows: list[list[str | None]],
    *,
    table: str = "securables",
) -> list:
    link = _link("https://presigned.example/chunk-0")
    client = FakeWorkspaceClient(
        FakeStatementExecution(execute=[_succeeded(columns, [link])])
    )
    reader = _reader(client, download=_downloader({link.external_link: body_rows}))
    return list(reader.read(table))


# --- parse_target_schema


def test_warehouse_splits_plain_target_schema_into_catalog_and_schema():
    assert parse_target_schema("cat.schema") == ("cat", "schema")


def test_warehouse_splits_backtick_quoted_target_schema_parts():
    assert parse_target_schema("`my-cat`.state") == ("my-cat", "state")


@pytest.mark.parametrize("target", ["cat", "a.b.c", "", ".s"])
def test_warehouse_rejects_malformed_target_schema(target):
    with pytest.raises(DumpReadError):
        parse_target_schema(target)


# --- WarehouseDumpReader


def test_warehouse_dump_reader_source_is_the_target_schema():
    reader = _reader(FakeWorkspaceClient(FakeStatementExecution()))

    assert reader.source == TARGET


def test_warehouse_dump_reader_reads_fully_quoted_table_name_on_given_warehouse():
    link = _link("https://presigned.example/chunk-0")
    statements = FakeStatementExecution(
        execute=[_succeeded([("name", ColumnInfoTypeName.STRING)], [link])]
    )
    reader = _reader(
        FakeWorkspaceClient(statements),
        download=_downloader({link.external_link: []}),
    )

    reader.read("securables")

    assert len(statements.executed) == 1
    call = statements.executed[0]
    assert "SELECT" in call["statement"].upper()
    assert "`cat`.`schema`.`securables`" in call["statement"]
    assert call["warehouse_id"] == WAREHOUSE_ID


def test_warehouse_dump_reader_converts_array_columns_to_tuples():
    rows = _read_one_chunk(
        [("grants", ColumnInfoTypeName.ARRAY)],
        [['["a","b"]']],
    )

    assert rows[0]["grants"] == ("a", "b")


def test_warehouse_dump_reader_converts_null_values_to_none():
    rows = _read_one_chunk(
        [("name", ColumnInfoTypeName.STRING), ("grants", ColumnInfoTypeName.ARRAY)],
        [[None, None]],
    )

    assert rows[0]["name"] is None
    assert rows[0]["grants"] is None


def test_warehouse_dump_reader_converts_boolean_text_to_bool():
    rows = _read_one_chunk(
        [
            ("enabled", ColumnInfoTypeName.BOOLEAN),
            ("disabled", ColumnInfoTypeName.BOOLEAN),
        ],
        [["true", "false"]],
    )

    assert rows[0]["enabled"] is True
    assert rows[0]["disabled"] is False


def test_warehouse_dump_reader_converts_integer_columns_to_int():
    rows = _read_one_chunk(
        [("rank", ColumnInfoTypeName.INT), ("big", ColumnInfoTypeName.LONG)],
        [["3", "9000000000"]],
    )

    assert rows[0]["rank"] == 3
    assert rows[0]["big"] == 9000000000
    assert isinstance(rows[0]["rank"], int)
    assert isinstance(rows[0]["big"], int)


def test_warehouse_dump_reader_keeps_string_columns_as_strings():
    rows = _read_one_chunk([("name", ColumnInfoTypeName.STRING)], [["3"]])

    assert rows[0]["name"] == "3"
    assert isinstance(rows[0]["name"], str)


def test_warehouse_dump_reader_keys_rows_by_column_name():
    rows = _read_one_chunk(
        [
            ("securable_name", ColumnInfoTypeName.STRING),
            ("owner", ColumnInfoTypeName.STRING),
        ],
        [["a", "bob"], ["b", "alice"]],
    )

    assert rows == [
        {"securable_name": "a", "owner": "bob"},
        {"securable_name": "b", "owner": "alice"},
    ]


def test_warehouse_dump_reader_returns_rows_from_every_chunk_in_order():
    columns = [("name", ColumnInfoTypeName.STRING)]
    first = _link("https://presigned.example/chunk-0", next_chunk_index=1)
    second = _link("https://presigned.example/chunk-1", chunk_index=1)
    statements = FakeStatementExecution(
        execute=[_succeeded(columns, [first], next_chunk_index=1)],
        chunks={
            1: ResultData(
                chunk_index=1,
                external_links=[second],
                next_chunk_index=None,
            )
        },
    )
    reader = _reader(
        FakeWorkspaceClient(statements),
        download=_downloader(
            {
                first.external_link: [["a"], ["b"]],
                second.external_link: [["c"]],
            }
        ),
    )

    rows = reader.read("securables")

    assert [row["name"] for row in rows] == ["a", "b", "c"]
    assert [index for _, index in statements.chunk_requests] == [1]


def test_warehouse_dump_reader_returns_no_rows_when_statement_has_no_external_links():
    statements = FakeStatementExecution(
        execute=[_succeeded([("name", ColumnInfoTypeName.STRING)], [])]
    )
    reader = _reader(FakeWorkspaceClient(statements))

    assert reader.read("securables") == []


def test_warehouse_dump_reader_returns_no_rows_when_result_is_zero_rows():
    link = _link("https://presigned.example/chunk-0")
    statements = FakeStatementExecution(
        execute=[_succeeded([("name", ColumnInfoTypeName.STRING)], [link])]
    )
    reader = _reader(
        FakeWorkspaceClient(statements),
        download=_downloader({link.external_link: []}),
    )

    assert reader.read("securables") == []


def test_warehouse_dump_reader_polls_until_statement_succeeds():
    columns = [("name", ColumnInfoTypeName.STRING)]
    link = _link("https://presigned.example/chunk-0")
    statements = FakeStatementExecution(
        execute=[_status_only(StatementState.PENDING)],
        polls=[
            _status_only(StatementState.RUNNING),
            _succeeded(columns, [link]),
        ],
    )
    reader = _reader(
        FakeWorkspaceClient(statements),
        download=_downloader({link.external_link: [["a"]]}),
    )

    rows = reader.read("securables")

    assert [row["name"] for row in rows] == ["a"]
    assert statements.polled_statement_ids
    assert set(statements.polled_statement_ids) == {STATEMENT_ID}


def test_warehouse_dump_reader_raises_error_naming_table_when_statement_fails():
    message = (
        "[TABLE_OR_VIEW_NOT_FOUND] The table or view "
        "`cat`.`schema`.`securable_tags` cannot be found."
    )
    statements = FakeStatementExecution(
        execute=[_status_only(StatementState.FAILED, message=message)]
    )
    reader = _reader(FakeWorkspaceClient(statements))

    with pytest.raises(DumpReadError) as excinfo:
        reader.read("securable_tags")

    assert "securable_tags" in str(excinfo.value)


def test_warehouse_dump_reader_raises_timeout_naming_table_and_cancels_statement():
    statements = FakeStatementExecution(
        execute=[_status_only(StatementState.RUNNING)],
        default_poll=_status_only(StatementState.RUNNING),
    )
    reader = _reader(FakeWorkspaceClient(statements), statement_timeout_seconds=0)

    with pytest.raises(DumpReadError) as excinfo:
        reader.read("securable_tags")

    assert "securable_tags" in str(excinfo.value)
    assert "timed out" in str(excinfo.value)
    assert statements.canceled_statement_ids == [STATEMENT_ID]


def test_warehouse_dump_reader_raises_dump_read_error_when_statement_is_canceled():
    statements = FakeStatementExecution(execute=[_status_only(StatementState.CANCELED)])
    reader = _reader(FakeWorkspaceClient(statements))

    with pytest.raises(DumpReadError):
        reader.read("securables")


def test_warehouse_dump_reader_wraps_client_errors_in_dump_read_error():
    statements = FakeStatementExecution(
        execute=[NotFound("Warehouse wh-1 does not exist")]
    )
    reader = _reader(FakeWorkspaceClient(statements))

    with pytest.raises(DumpReadError):
        reader.read("securables")


# --- transient download failures


def _flaky_downloader(
    failures: list, body: bytes
) -> tuple[Callable[[str], bytes], list]:
    """A downloader that raises (or returns) each of ``failures`` in turn, then
    ``body``; it records every URL it was asked for."""
    calls: list[str] = []
    pending = list(failures)

    def download(url: str) -> bytes:
        calls.append(url)
        if pending:
            outcome = pending.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return body

    return download, calls


def _read_with(download: Callable[[str], bytes], **kwargs) -> list:
    link = _link("https://presigned.example/chunk-0")
    client = FakeWorkspaceClient(
        FakeStatementExecution(
            execute=[_succeeded([("name", ColumnInfoTypeName.STRING)], [link])]
        )
    )
    reader = WarehouseDumpReader(
        client,
        WAREHOUSE_ID,
        TARGET,
        poll_interval_seconds=0,
        statement_timeout_seconds=60.0,
        download=download,
        retry_delay_seconds=0,
        **kwargs,
    )
    return list(reader.read("principals"))


def test_warehouse_dump_reader_does_not_retry_a_client_error_download():
    not_found = urllib.error.HTTPError(
        "https://presigned.example/chunk-0", 403, "Forbidden", hdrs=None, fp=None
    )
    download, calls = _flaky_downloader([not_found], json.dumps([["a"]]).encode())

    with pytest.raises(DumpReadError):
        _read_with(download)

    assert len(calls) == 1


def test_warehouse_dump_reader_retries_a_server_error_download_then_succeeds():
    unavailable = urllib.error.HTTPError(
        "https://presigned.example/chunk-0", 503, "Unavailable", hdrs=None, fp=None
    )
    download, calls = _flaky_downloader([unavailable], json.dumps([["a"]]).encode())

    rows = _read_with(download)

    assert rows == [{"name": "a"}]
    assert len(calls) == 2


@pytest.mark.parametrize(
    "failure",
    [
        http.client.IncompleteRead(b"[[", 100),
        urllib.error.URLError("connection reset"),
        TimeoutError("timed out"),
        b'[["trunc',
    ],
    ids=["incomplete-read", "url-error", "timeout", "truncated-body"],
)
def test_warehouse_dump_reader_retries_a_transient_download_failure(failure):
    download, calls = _flaky_downloader([failure], json.dumps([["a"]]).encode())

    rows = _read_with(download)

    assert rows == [{"name": "a"}]
    assert len(calls) == 2


def test_warehouse_dump_reader_raises_after_repeated_download_failures():
    failure = http.client.IncompleteRead(b"[[", 100)
    download, calls = _flaky_downloader([failure] * 10, b"[]")

    with pytest.raises(DumpReadError, match="principals"):
        _read_with(download, download_attempts=3)

    assert len(calls) == 3
