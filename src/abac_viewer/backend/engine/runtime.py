"""App-lifecycle wiring for the factored model.

The model is loaded from the uc-abac dump tables (``WarehouseDumpReader``) as the app's
service principal and held in a ``ModelStore``. The first load runs in a background
thread at startup so the app answers immediately; until it finishes (or if it fails)
model-backed endpoints return 503 with the reason. ``refresh`` reloads on demand and
swaps the new model in atomically; a failed refresh keeps serving the previous model.

Settings come from ``AppConfig`` (env prefix ``ABAC_VIEWER_``): ``TARGET_SCHEMA`` and
``WAREHOUSE_ID`` locate the dump; ``REPO_SLUG`` / ``REPO_REF`` / ``CONFIG_PATH_PREFIX``
describe where the config repository lives on GitHub, for source deep links
(``config_file_path`` in the dump is relative to the directory ``uc-abac dump`` ran in,
so the prefix maps it to its repository path).
"""

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, TypeAlias

from databricks.sdk import WorkspaceClient
from fastapi import Depends, FastAPI, HTTPException, Request

from abac_viewer.backend.core._base import LifespanDependency
from abac_viewer.backend.core._config import AppConfig, logger
from abac_viewer.backend.engine.dump import load_factored_model_from_dump
from abac_viewer.backend.engine.model import FactoredModel
from abac_viewer.backend.engine.warehouse import WarehouseDumpReader


@dataclass(frozen=True)
class BuildInfo:
    """Where the config tree lives on GitHub, for chain-node deep links."""

    sha: str  # git ref (commit SHA, tag, or branch) the links pin to
    repo_slug: str  # e.g. example-org/abac-configs; empty disables links
    config_path_prefix: str  # maps a config_file_path to its repository location

    def github_url(self, config_file_path: str, line: int | None = None) -> str | None:
        """The GitHub blob URL of a config file (anchored to ``line`` when given), or
        None without a repository slug."""
        if not self.repo_slug:
            return None
        path = f"{self.config_path_prefix}/{config_file_path}".strip("/")
        url = f"https://github.com/{self.repo_slug}/blob/{self.sha}/{path}"
        return f"{url}#L{line}" if line else url


class ModelUnavailableError(RuntimeError):
    """No model is loaded yet: the first load is still running or it failed."""


@dataclass(frozen=True)
class StoreStatus:
    """A snapshot of the store: when the current model loaded (None before the first
    successful load), the last load error (None after a success), and whether a load
    is in progress."""

    loaded_at: datetime | None
    error: str | None
    loading: bool


def _describe_error(error: Exception) -> str:
    """The error message, or the exception type name when the message is empty."""
    return str(error) or type(error).__name__


class ModelStore:
    """Holds the current model and reloads it with ``load``. Thread-safe.

    Loads run one at a time under ``_load_lock``, so a refresh that starts while
    another load is running waits for it and then loads again: the most recently
    started load is always the one recorded last. ``_in_flight`` counts refreshes
    that have started and not yet recorded an outcome, including ones still waiting
    for ``_load_lock``; ``status.loading`` is true while it is non-zero.
    """

    def __init__(self, load: Callable[[], FactoredModel]):
        self._load = load
        self._lock = threading.Lock()  # guards the fields below
        self._load_lock = threading.Lock()  # serialises the loader calls
        self._model: FactoredModel | None = None
        self._loaded_at: datetime | None = None
        self._error: str | None = None
        self._in_flight = 0

    def _begin_load(self) -> None:
        """Count a refresh as in flight from the moment it is requested."""
        with self._lock:
            self._in_flight += 1

    def _record_success(self, model: FactoredModel) -> None:
        """Swap in ``model``, clear the recorded error and finish one in-flight load."""
        with self._lock:
            self._model = model
            self._loaded_at = datetime.now(UTC)
            self._error = None
            self._in_flight -= 1

    def _record_failure(self, error: Exception) -> str:
        """Record ``error`` while keeping any previous model, finish one in-flight
        load, and return the message."""
        message = _describe_error(error)
        with self._lock:
            self._error = message
            self._in_flight -= 1
        return message

    def _load_and_record(self) -> FactoredModel:
        """Run the loader under ``_load_lock`` and record its outcome. The caller must
        already have counted the load with ``_begin_load``."""
        with self._load_lock:
            try:
                model = self._load()
            except Exception as error:
                message = self._record_failure(error)
                raise ModelUnavailableError(
                    f"model failed to load: {message}"
                ) from error
            self._record_success(model)
        return model

    def get(self) -> FactoredModel:
        """The current model; raises ``ModelUnavailableError`` (with the load error,
        or a still-loading message) when none has loaded."""
        with self._lock:
            if self._model is not None:
                return self._model
            error = self._error
        if error is not None:
            raise ModelUnavailableError(f"model failed to load: {error}")
        raise ModelUnavailableError("model is still loading")

    def refresh(self) -> FactoredModel:
        """Load synchronously and swap the result in. On failure the previous model
        (if any) stays current, the error is recorded in ``status``, and
        ``ModelUnavailableError`` is raised. Waits behind any load already running."""
        self._begin_load()
        return self._load_and_record()

    def refresh_in_background(self) -> None:
        """Start ``refresh`` in a daemon thread, logging rather than raising errors.
        A no-op while a load is already running or waiting to run.

        The in-flight count is taken here, under the lock, rather than on the new
        thread, so two calls in a row cannot both start a load.
        """
        with self._lock:
            if self._in_flight:
                return
            self._in_flight += 1
        threading.Thread(
            target=self._run_counted_load, name="model-store-refresh", daemon=True
        ).start()

    def _run_counted_load(self) -> None:
        """The background body: a load already counted by ``refresh_in_background``."""
        try:
            self._load_and_record()
        except ModelUnavailableError as error:
            logger.error(f"Model refresh failed: {error}")

    @property
    def status(self) -> StoreStatus:
        with self._lock:
            return StoreStatus(
                loaded_at=self._loaded_at,
                error=self._error,
                loading=self._in_flight > 0,
            )


# ---------------------------------------------------------------------------
# FastAPI wiring
# ---------------------------------------------------------------------------


def build_info_from_config(config: AppConfig) -> BuildInfo:
    """The GitHub deep-link settings from the app config.

    Databricks Apps reject an empty environment variable value, so the bundle passes
    ``none`` for "no repository" (links off) and ``.`` for "the repository root"; both
    are normalised to the empty string here.
    """
    slug = "" if config.repo_slug.lower() == "none" else config.repo_slug
    prefix = config.config_path_prefix
    prefix = "" if prefix in (".", "./") else prefix.removeprefix("./")
    return BuildInfo(sha=config.repo_ref, repo_slug=slug, config_path_prefix=prefix)


def dump_model_loader(config: AppConfig) -> Callable[[], FactoredModel]:
    """A loader reading the dump tables as the app's service principal. Loading fails,
    naming the settings, when the target schema or warehouse is not configured."""

    def load() -> FactoredModel:
        if not (config.target_schema and config.warehouse_id):
            raise ValueError(
                "ABAC_VIEWER_TARGET_SCHEMA and ABAC_VIEWER_WAREHOUSE_ID must be set"
            )
        reader = WarehouseDumpReader(
            WorkspaceClient(), config.warehouse_id, config.target_schema
        )
        model = load_factored_model_from_dump(reader)
        logger.info(
            f"Loaded model {model.revision} from {model.source}: "
            f"{len(model.securables)} securables, "
            f"{len(model.grant_policies) + len(model.fgac_policies)} policies, "
            f"{len(model.grant_matches)} grant matches, {len(model.drift)} drift"
        )
        for warning in model.warnings:
            logger.warning(f"dump warning: {warning}")
        for item in model.drift:
            logger.warning(
                f"dump drift: policy {item.policy_id} expects {item.privilege} on "
                f"{item.securable_full_name} for {item.principal}, which Unity Catalog "
                "does not hold"
            )
        return model

    return load


class _ModelStoreDependency(LifespanDependency):
    """Creates the ModelStore at startup and starts the first load in the background."""

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        config = AppConfig()
        app.state.model_store = ModelStore(dump_model_loader(config))
        app.state.build_info = build_info_from_config(config)
        app.state.model_store.refresh_in_background()
        yield

    @staticmethod
    def __call__(request: Request) -> ModelStore:
        return request.app.state.model_store


def get_model_store(request: Request) -> ModelStore:
    """The app's ModelStore."""
    return request.app.state.model_store


def get_model(store: Annotated[ModelStore, Depends(get_model_store)]) -> FactoredModel:
    """The current model, or 503 with the reason while none is available."""
    try:
        return store.get()
    except ModelUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def get_build_info(request: Request) -> BuildInfo:
    """The GitHub deep-link settings."""
    return request.app.state.build_info


ModelStoreDependency: TypeAlias = Annotated[ModelStore, Depends(get_model_store)]
ModelDependency: TypeAlias = Annotated[FactoredModel, Depends(get_model)]
BuildInfoDependency: TypeAlias = Annotated[BuildInfo, Depends(get_build_info)]
