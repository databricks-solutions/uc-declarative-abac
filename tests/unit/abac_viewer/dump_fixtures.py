"""Test support: turn a YAML config tree into ``uc-abac dump`` table rows.

The viewer reads the tables ``uc-abac dump`` writes. To exercise it end to end without
a workspace, this module simulates a deployment that matches the config exactly: it
compiles the desired state with the engine's own compilers, resolves every principal
name, and projects that state through the dumper's own row builders
(``uc_abac.dumper.TABLE_SPECS``). The rows are therefore shaped exactly as a real dump
would write them for a workspace that has the config fully applied.

Principals are resolved as groups when the config declares them (or for the
``account users`` system group), as service principals when listed in
``service_principals`` (with a deterministic UUID application id, mirroring how a real
dump writes service principals by application id), and as users otherwise.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import replace
from datetime import date
from pathlib import Path

from abac_viewer.backend.engine.dump import (
    InMemoryDumpReader,
    load_factored_model_from_dump,
)
from abac_viewer.backend.engine.model import FactoredModel
from uc_abac.dumper import TABLE_SPECS, Row, build_dump_context
from uc_abac.governed_tags import compile_desired_governed_tags
from uc_abac.logger import ChangeLogger
from uc_abac.orchestrator import ActualState, load_config
from uc_abac.policies import compile_desired_policies
from uc_abac.principals import Principal, compile_desired_groups
from uc_abac.privileges import compile_desired_privileges
from uc_abac.securables import compile_desired_attributes, compile_desired_securables
from uc_abac.tags import compile_desired_tags
from uc_abac.types import PrincipalType

DumpRows = dict[str, list[Row]]

_RUN_DATE = date(2026, 1, 1)
_SYSTEM_GROUPS = frozenset({"account users", "account admins"})


def application_id(service_principal_name: str) -> str:
    """The deterministic application id given to a simulated service principal."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sp:{service_principal_name}"))


class _Resolver:
    """Resolves config display names to synthetic, fully-resolved principals."""

    def __init__(self, group_names: set[str], service_principals: set[str]):
        self._group_names = group_names | _SYSTEM_GROUPS
        self._service_principals = service_principals
        self.resolved: dict[str, Principal] = {}

    def __call__(self, principal: Principal) -> Principal:
        name = principal.name or principal.identifier
        if name not in self.resolved:
            self.resolved[name] = self._resolve_name(name)
        return self.resolved[name]

    def _resolve_name(self, name: str) -> Principal:
        if name in self._group_names:
            kind, identifier = PrincipalType.GROUP, name
        elif name in self._service_principals:
            kind, identifier = PrincipalType.SERVICE_PRINCIPAL, application_id(name)
        else:
            kind, identifier = PrincipalType.USER, name
        return Principal(
            principal_type=kind,
            identifier=identifier,
            name=name,
            internal_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"id:{name}").int % 10**12),
        )


def _resolved_members(members: frozenset[Principal] | None, resolve: _Resolver):
    return None if members is None else frozenset(resolve(m) for m in members)


def build_actual_state(
    config_dir: Path,
    run_date: date = _RUN_DATE,
    service_principals: Iterable[str] = (),
):
    """Compile ``config_dir`` into the ``ActualState`` of a matching deployment, and
    return it with the loaded config."""
    config = load_config(config_dir)
    change_logger = ChangeLogger(dry_run=True, logger=logging.getLogger(__name__))
    governed_tags = compile_desired_governed_tags(config)
    governed_names = {tag.name for tag in governed_tags}
    tags = compile_desired_tags(config, governed_tags, change_logger)
    groups = compile_desired_groups(config, run_date)
    resolve = _Resolver({g.display_name for g in groups}, set(service_principals))

    privileges = {
        replace(p, principal=resolve(p.principal))
        for p in compile_desired_privileges(
            config, tags, governed_names, change_logger, run_date
        )
    }
    policies = {
        replace(
            p,
            to_principals=tuple(resolve(x) for x in p.to_principals),
            except_principals=tuple(resolve(x) for x in p.except_principals),
        )
        for p in compile_desired_policies(config, governed_names, change_logger)
    }
    resolved_groups = frozenset(
        replace(
            g,
            members=_resolved_members(g.members, resolve),
            assumers=_resolved_members(g.assumers, resolve),
        )
        for g in groups
    )
    state = ActualState(
        groups=resolved_groups,
        all_account_groups=resolved_groups,
        governed_tags=frozenset(governed_tags),
        domains=frozenset(),
        securables=frozenset(compile_desired_securables(config)),
        attributes=frozenset(compile_desired_attributes(config)),
        tags=frozenset(tags),
        policies=frozenset(policies),
        privileges=frozenset(privileges),
        principals=dict(resolve.resolved),
    )
    return state, config


def dump_rows_from_state(
    state: ActualState, config, run_date: date = _RUN_DATE
) -> DumpRows:
    """Project ``state`` through the dumper's row builders, keyed by table name."""
    context = build_dump_context(state, config, run_date)
    return {spec.name: spec.rows(state, context) for spec in TABLE_SPECS}


def _relative_to_cwd(path: Path) -> Path:
    """Dump rows carry config paths as given to ``uc-abac dump`` (typically relative
    to the repository root), so fixtures are compiled with a cwd-relative path."""
    try:
        return path.resolve().relative_to(Path.cwd())
    except ValueError:
        return path


def dump_rows_from_config(
    config_dir: Path,
    run_date: date = _RUN_DATE,
    service_principals: Iterable[str] = (),
) -> DumpRows:
    """The rows ``uc-abac dump`` would write for a deployment matching ``config_dir``."""
    relative_dir = _relative_to_cwd(config_dir)
    state, config = build_actual_state(relative_dir, run_date, service_principals)
    return dump_rows_from_state(state, config, run_date)


def load_dump_model(
    config_dir: Path, service_principals: Iterable[str] = ()
) -> FactoredModel:
    """Load the viewer model from a simulated dump of ``config_dir``."""
    rows = dump_rows_from_config(config_dir, service_principals=service_principals)
    return load_factored_model_from_dump(InMemoryDumpReader(rows))
