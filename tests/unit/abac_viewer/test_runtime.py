"""ModelStore lifecycle and the get_model FastAPI dependency."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest
from fastapi import HTTPException

from abac_viewer.backend.core._config import AppConfig
from abac_viewer.backend.engine.model import FactoredModel
from abac_viewer.backend.engine.runtime import (
    ModelStore,
    ModelUnavailableError,
    dump_model_loader,
    get_model,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(revision: str = "r1") -> FactoredModel:
    return FactoredModel(revision=revision, source="s")


def _failing_loader() -> Callable[[], FactoredModel]:
    def load() -> FactoredModel:
        raise RuntimeError("warehouse unreachable")

    return load


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _background_loads_finished(timeout: float = 2.0) -> bool:
    """Whether every background refresh thread has exited, so a late recording has
    landed before the test asserts (``refresh_in_background`` runs on a daemon thread
    named ``model-store-refresh``)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(
            t.name == "model-store-refresh" and t.is_alive()
            for t in threading.enumerate()
        ):
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------------------
# ModelStore: synchronous loads
# ---------------------------------------------------------------------------


def test_model_store_get_raises_unavailable_before_any_load():
    store = ModelStore(lambda: _model())

    with pytest.raises(ModelUnavailableError):
        store.get()


def test_model_store_status_is_empty_before_any_load():
    store = ModelStore(lambda: _model())

    status = store.status

    assert status.loaded_at is None
    assert status.error is None


def test_model_store_refresh_returns_model_and_get_serves_it():
    model = _model("r1")
    store = ModelStore(lambda: model)

    refreshed = store.refresh()

    assert refreshed is model
    assert store.get() is model
    assert store.status.loaded_at is not None
    assert store.status.error is None


def test_model_store_refresh_raises_unavailable_when_loader_fails():
    store = ModelStore(_failing_loader())

    with pytest.raises(ModelUnavailableError):
        store.refresh()


def test_model_store_status_records_error_when_loader_fails():
    store = ModelStore(_failing_loader())

    with pytest.raises(ModelUnavailableError):
        store.refresh()

    assert store.status.error is not None
    assert "warehouse unreachable" in store.status.error
    assert store.status.loaded_at is None


def test_model_store_get_reports_load_failure_reason():
    store = ModelStore(_failing_loader())

    with pytest.raises(ModelUnavailableError):
        store.refresh()

    with pytest.raises(ModelUnavailableError, match="warehouse unreachable"):
        store.get()


def test_model_store_failed_refresh_keeps_serving_previous_model():
    good = _model("r1")
    outcomes = iter([good, RuntimeError("transient failure")])

    def load() -> FactoredModel:
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    store = ModelStore(load)
    store.refresh()

    with pytest.raises(ModelUnavailableError):
        store.refresh()

    assert store.get() is good
    assert store.status.error is not None
    assert "transient failure" in store.status.error


def test_model_store_successful_refresh_after_failure_clears_error_and_swaps_model():
    old = _model("r1")
    new = _model("r2")
    outcomes = iter([old, RuntimeError("transient failure"), new])

    def load() -> FactoredModel:
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    store = ModelStore(load)
    store.refresh()
    with pytest.raises(ModelUnavailableError):
        store.refresh()

    current = store.refresh()

    assert current is new
    assert store.get() is new
    assert store.status.error is None


# ---------------------------------------------------------------------------
# ModelStore: background loads
# ---------------------------------------------------------------------------


def test_model_store_refresh_in_background_loads_model():
    model = _model()
    store = ModelStore(lambda: model)

    store.refresh_in_background()

    assert _wait_until(lambda: store.status.loaded_at is not None)
    assert store.get() is model
    assert store.status.error is None


def test_model_store_refresh_in_background_does_not_start_second_load_while_loading():
    release = threading.Event()
    started = threading.Event()
    calls: list[int] = []
    model = _model()

    def slow_load() -> FactoredModel:
        calls.append(1)
        started.set()
        release.wait(timeout=5)
        return model

    store = ModelStore(slow_load)

    store.refresh_in_background()
    assert started.wait(timeout=2)
    assert store.status.loading is True

    store.refresh_in_background()
    release.set()

    assert _wait_until(lambda: store.status.loaded_at is not None)
    assert store.status.loading is False
    assert len(calls) == 1


def test_model_store_refresh_in_background_does_not_raise_when_loader_fails():
    store = ModelStore(_failing_loader())

    store.refresh_in_background()

    assert _wait_until(lambda: store.status.error is not None)
    assert "warehouse unreachable" in store.status.error
    assert store.status.loaded_at is None


def test_model_store_reloads_in_background_after_a_failed_background_load():
    calls: list[int] = []

    def load() -> FactoredModel:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("warehouse unreachable")
        return _model("r2")

    store = ModelStore(load)

    store.refresh_in_background()
    assert _wait_until(lambda: store.status.error is not None)
    assert _background_loads_finished()
    assert store.status.loading is False

    store.refresh_in_background()
    assert _wait_until(lambda: store.status.loaded_at is not None)
    assert store.get().revision == "r2"


def test_model_store_last_started_load_wins_when_an_earlier_load_finishes_later():
    release = threading.Event()
    entered = threading.Event()
    first, second = _model("r1"), _model("r2")
    calls: list[int] = []

    def load() -> FactoredModel:
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            release.wait(timeout=5)
            return first
        return second

    store = ModelStore(load)
    later = threading.Thread(target=store.refresh, daemon=True)
    try:
        store.refresh_in_background()
        assert entered.wait(timeout=2)
        assert store.status.loading is True

        later.start()
        time.sleep(0.05)
    finally:
        release.set()
    later.join(timeout=5)

    assert not later.is_alive()
    assert _background_loads_finished()
    assert store.get() is second
    assert store.status.loading is False


# ---------------------------------------------------------------------------
# get_model FastAPI dependency
# ---------------------------------------------------------------------------


def test_runtime_get_model_returns_current_model():
    model = _model()
    store = ModelStore(lambda: model)
    store.refresh()

    assert get_model(store) is model


def test_runtime_get_model_raises_503_with_reason_when_load_failed():
    store = ModelStore(_failing_loader())
    store.refresh_in_background()
    assert _wait_until(lambda: store.status.error is not None)

    with pytest.raises(HTTPException) as excinfo:
        get_model(store)

    assert excinfo.value.status_code == 503
    assert "warehouse unreachable" in str(excinfo.value.detail)


def test_runtime_get_model_raises_503_when_no_load_has_started():
    store = ModelStore(lambda: _model())

    with pytest.raises(HTTPException) as excinfo:
        get_model(store)

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail


# ---------------------------------------------------------------------------
# dump_model_loader
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target_schema", "warehouse_id"),
    [("", ""), ("cat.state", ""), ("", "abc123")],
)
def test_runtime_dump_model_loader_names_missing_settings(target_schema, warehouse_id):
    config = AppConfig(target_schema=target_schema, warehouse_id=warehouse_id)
    store = ModelStore(dump_model_loader(config))

    with pytest.raises(ModelUnavailableError):
        store.refresh()

    assert "ABAC_VIEWER_TARGET_SCHEMA" in store.status.error
    assert "ABAC_VIEWER_WAREHOUSE_ID" in store.status.error
