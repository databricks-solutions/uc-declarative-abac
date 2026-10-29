"""Model refresh and availability over the HTTP API."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from abac_viewer.backend.engine.model import FactoredModel
from abac_viewer.backend.engine.runtime import (
    BuildInfo,
    ModelStore,
    get_build_info,
    get_model_store,
)
from abac_viewer.backend.router import router


def _client(load: Callable[[], FactoredModel]) -> tuple[TestClient, ModelStore]:
    store = ModelStore(load)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_model_store] = lambda: store
    app.dependency_overrides[get_build_info] = lambda: BuildInfo("main", "", "")
    return TestClient(app), store


def _failing_load() -> FactoredModel:
    raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND: securables")


# ---------------------------------------------------------------------------
# refresh endpoint
# ---------------------------------------------------------------------------


def test_router_refresh_loads_the_model_and_returns_its_metadata():
    client, _ = _client(lambda: FactoredModel(revision="r1", source="cat.state"))

    response = client.post("/api/refresh")

    assert response.status_code == 200
    assert response.json()["revision"] == "r1"
    assert response.json()["source"] == "cat.state"
    assert client.get("/api/meta").json()["revision"] == "r1"


def test_router_refresh_serves_the_reloaded_model():
    revisions = iter(["r1", "r2"])
    client, _ = _client(lambda: FactoredModel(revision=next(revisions), source="s"))

    client.post("/api/refresh")
    client.post("/api/refresh")

    assert client.get("/api/meta").json()["revision"] == "r2"


def test_router_refresh_returns_503_with_the_reason_when_loading_fails():
    client, _ = _client(_failing_load)

    response = client.post("/api/refresh")

    assert response.status_code == 503
    assert "TABLE_OR_VIEW_NOT_FOUND" in response.json()["detail"]


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/meta", "/api/principals", "/api/tables"])
def test_router_model_endpoints_return_503_before_the_model_loads(path):
    client, _ = _client(_failing_load)

    response = client.get(path)

    assert response.status_code == 503
    assert response.json()["detail"]
