"""Databricks Apps request headers, read through the public ``Dependencies.Headers``."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from abac_viewer.backend.core import Dependencies


def _client() -> TestClient:
    """An app whose only route echoes the parsed ``X-Request-Id`` header."""
    app = FastAPI()

    @app.get("/request-id")
    def echo(headers: Dependencies.Headers) -> dict:
        return {"request_id": headers.request_id}

    return TestClient(app)


def test_headers_request_id_is_parsed_to_uuid():
    raw = str(uuid.uuid4()).upper()

    response = _client().get("/request-id", headers={"X-Request-Id": raw})

    assert response.status_code == 200
    assert response.json()["request_id"] == str(uuid.UUID(raw))


def test_headers_non_uuid_request_id_is_none():
    response = _client().get("/request-id", headers={"X-Request-Id": "abc123"})

    assert response.status_code == 200
    assert response.json()["request_id"] is None
