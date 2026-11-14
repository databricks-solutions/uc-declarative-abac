from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uc_abac.logger import ChangeLogger
    from uc_abac.resources.principals import PrincipalResolver

from uc_abac.errors import (
    ExecutionError,
    NonexistentSecurableError,
    OrchestratorError,
    PrincipalValidationError,
)
from uc_abac.resources.principals import log_principal_resolution_failure
from uc_abac.resources.securables.resolver import render_function_bodies
from uc_abac.resources.securables.state import (
    AttributeUpdate,
    Column,
    Function,
    Securable,
    SecurableAttributes,
    SecurableDiff,
    SecurableKey,
    Table,
)
from uc_abac.types import SecurableType
from uc_abac.utils import Scope

_GOVERNED_ATTRIBUTES = [
    "owner",
    "comment",
    "rfa_destinations",
    "data_classification_enabled",
    "data_classification_excluded_schemas",
    "data_classification_included_schemas",
    "data_classification_auto_tagging_tags",
]

# Governed attributes whose value is already a frozenset (diffed as a whole set).
_COLLECTION_ATTRIBUTES = frozenset(
    {
        "rfa_destinations",
        "data_classification_excluded_schemas",
        "data_classification_included_schemas",
        "data_classification_auto_tagging_tags",
    }
)

# Empty (inert) scope: the default when creation is disabled — matches nothing.
_EMPTY_SCOPE = Scope()


def _to_frozenset(attr: str, value: object) -> frozenset:
    """Wrap a SecurableAttributes field value into a frozenset for diff comparison.

    Scalar fields (``owner``, ``comment``, ``data_classification_enabled``) become
    a 1-element frozenset, or an empty frozenset when the value is missing / empty.
    Collection fields (``_COLLECTION_ATTRIBUTES``) pass through as the natural
    frozenset (``None`` → empty). This keeps the diff loop attribute-agnostic and lets the executor
    take a uniform set-shaped value.
    """
    if attr in _COLLECTION_ATTRIBUTES:
        return value if value is not None else frozenset()
    if value is None or value == "":
        return frozenset()
    return frozenset({value})


# ``information_schema.tables.table_type`` values that don't support ``COMMENT ON TABLE …``
# / ``ALTER TABLE … SET COMMENT`` via the path this engine uses. Today only regular VIEWs are
# affected.
_COMMENT_IMMUTABLE_TABLE_TYPES = frozenset({"VIEW", "METRIC_VIEW"})

# ``information_schema.tables.table_type`` values that don't support ``ALTER TABLE … OWNER TO``
# via the SDK paths this engine uses. Regular VIEW *does* support owner changes via
# ``ALTER VIEW … OWNER TO`` and is intentionally excluded.
_OWNER_IMMUTABLE_TABLE_TYPES = frozenset({"MATERIALIZED_VIEW", "STREAMING_TABLE"})


def compute_securable_diff(
    desired_attrs: set[SecurableAttributes],
    actual_attrs: set[SecurableAttributes],
    desired_securables: set[Securable],
    actual_securables: set[Securable],
    resolver: PrincipalResolver,
    change_logger: ChangeLogger,
    creation_in_scope_namespaces: Scope = _EMPTY_SCOPE,
    ignore_unresolvable: frozenset[str] = frozenset(),
    warn_on_nonexistent_securables: bool = False,
) -> SecurableDiff:
    """Compute the diff between desired and actual securable state.

    Resolves owner Principals on both sides before diffing. Owner-resolution
    failures are logged via change_logger and clear the owner field on the
    affected row (the SecurableAttributes itself is retained so the securable's
    create/replace info isn't lost). ``ignore_unresolvable`` silences the
    resolution-failure warning for the listed actual-state identifiers (the owner
    is still cleared) — used for unresolvable Databricks-managed system service
    principals that own securables.

    Non-function securables declared in config but absent from UC are created
    only if their namespace is in ``creation_in_scope_namespaces``; out-of-scope
    namespaces (and the all-empty set, which is the default and means "creation
    disabled for everything") log ``NonexistentSecurableError`` and are dropped
    from ``securables_to_create``. With ``warn_on_nonexistent_securables``, those
    out-of-scope errors become warnings and their typed identities are returned
    for downstream pruning. Functions are always engine-managed and flow through
    regardless of scope. Tables require ≥1 column and every column must have a
    non-None ``type``. In-scope tables that fail this check remain fatal errors.
    """
    desired_attrs = _resolve_attribute_owners(
        desired_attrs, resolver, change_logger, ignore_unresolvable
    )
    actual_attrs = _resolve_attribute_owners(
        actual_attrs, resolver, change_logger, ignore_unresolvable
    )

    desired_securables = render_function_bodies(
        desired_securables, resolver, change_logger, ignore_unresolvable
    )
    securables_to_create, securables_to_replace, old_securables = _diff_securables(
        desired_securables, actual_securables
    )
    creatable, blocked = _partition_by_creation_scope(
        securables_to_create,
        creation_in_scope_namespaces,
    )
    creatable = _validate_tables_for_creation(creatable, change_logger)
    nonexistent_securables = _log_nonexistent_non_function_securables(
        blocked,
        change_logger,
        warn_on_nonexistent_securables,
    )
    securables_to_create = creatable

    table_full_names_being_created = {
        s.full_name
        for s in securables_to_create
        if s.securable_type == SecurableType.TABLE
    }
    columns_to_create, nonexistent_columns = _diff_table_columns(
        desired_securables,
        actual_securables,
        table_full_names_being_created,
        change_logger,
        creation_in_scope_namespaces,
        warn_on_nonexistent_securables,
    )
    securables_to_create.extend(columns_to_create)
    nonexistent_securables = nonexistent_securables.union(nonexistent_columns)

    created_full_names = {s.full_name for s in securables_to_create}

    view_full_names = {
        s.full_name
        for s in actual_securables
        if isinstance(s, Table) and s.table_type in _COMMENT_IMMUTABLE_TABLE_TYPES
    }
    owner_immutable_full_names = {
        s.full_name
        for s in actual_securables
        if isinstance(s, Table) and s.table_type in _OWNER_IMMUTABLE_TABLE_TYPES
    }

    attributes_to_update = _diff_attributes(
        desired_attrs,
        actual_attrs,
        created_full_names,
        view_full_names=view_full_names,
        owner_immutable_full_names=owner_immutable_full_names,
        change_logger=change_logger,
    )

    return SecurableDiff(
        attributes_to_update=attributes_to_update,
        securables_to_create=securables_to_create,
        securables_to_replace=securables_to_replace,
        old_securables=old_securables,
        nonexistent_securables=nonexistent_securables,
    )


def _resolve_attribute_owners(
    unresolved: set[SecurableAttributes],
    resolver: PrincipalResolver,
    change_logger: ChangeLogger,
    ignore_unresolvable: frozenset[str] = frozenset(),
) -> set[SecurableAttributes]:
    """Resolve owner Principals on a set of SecurableAttributes.

    On failure, clears the owner field but retains the SecurableAttributes —
    dropping it would lose the securable's create/replace info. The
    resolution-failure warning is suppressed for owners whose identifier is in
    ``ignore_unresolvable`` (the owner is still cleared).

    Uses ``dataclasses.replace`` so every non-owner field (``comment``,
    ``rfa_destinations``, …) on the input survives owner resolution.
    Reconstructing from scratch here silently dropped those fields and broke
    idempotency for every managed attribute other than ``owner`` itself.
    """
    result: set[SecurableAttributes] = set()
    for attr in unresolved:
        if attr.owner is None:
            result.add(attr)
            continue
        try:
            resolved_owner = resolver.resolve_principal(attr.owner)
        except PrincipalValidationError as exc:
            log_principal_resolution_failure(
                change_logger,
                f"Resolve owner for {attr.securable_type.value} {attr.full_name}",
                attr.owner,
                exc,
                ignore_unresolvable,
            )
            result.add(dataclasses.replace(attr, owner=None))
            continue
        result.add(dataclasses.replace(attr, owner=resolved_owner))
    return result


def _diff_securables(
    desired: set[Securable],
    actual: set[Securable],
) -> tuple[list[Securable], list[Securable], dict[str, Securable]]:
    """Return (to_create, to_replace, old_securables) by keying on (securable_type, full_name).

    Replacement is function-only today: tables, volumes, catalogs, and schemas don't
    support in-place redefinition, and a Table with declared columns can't be
    meaningfully compared to a base ``Securable`` fetched from UC (which lacks column
    info). ``old_securables`` is typed generically so future replaceable types can be
    added without reshaping the diff. The matched prior state is captured in
    ``old_securables`` so the executor can pass it to the logger for a per-field
    replace diff.
    """
    actual_by_key = {(s.securable_type, s.full_name): s for s in actual}

    to_create: list[Securable] = []
    to_replace: list[Securable] = []
    old_securables: dict[str, Securable] = {}

    for desired_sec in desired:
        actual_sec = actual_by_key.get(
            (desired_sec.securable_type, desired_sec.full_name)
        )
        if actual_sec is None:
            to_create.append(desired_sec)
        elif isinstance(desired_sec, Function) and desired_sec != actual_sec:
            to_replace.append(desired_sec)
            if actual_sec is not None:
                old_securables[desired_sec.full_name] = actual_sec

    return to_create, to_replace, old_securables


def _table_creation_blocker(table: Table) -> str | None:
    """Return a reason string if ``table`` cannot be validly created, else None.

    A creatable Table must have at least one column and every column must declare
    its UC datatype via the ``data_type`` field.
    """
    if not table.columns:
        return "Configure at least one column with a 'type' to enable table creation."
    untyped = [c.full_name for c in table.columns if not c.data_type]
    if untyped:
        return (
            f"Column(s) {', '.join(repr(n) for n in untyped)} declared without a 'type' — "
            "every column must specify its UC datatype to enable table creation."
        )
    return None


def _column_creation_blocker(column: Column) -> str | None:
    """Return a reason string if ``column`` cannot be validly created via
    ALTER TABLE ADD COLUMN, else None. A creatable column must declare its
    UC datatype via the ``data_type`` field — ALTER TABLE syntax requires it."""
    if not column.data_type:
        return "Declare a 'type' on the column to enable creation."
    return None


def _diff_table_columns(
    desired: set[Securable],
    actual: set[Securable],
    table_full_names_being_created: set[str],
    change_logger: ChangeLogger,
    creation_in_scope_namespaces: Scope,
    warn_on_nonexistent_securables: bool,
) -> tuple[list[Column], frozenset[SecurableKey]]:
    """For each desired Table that already exists in UC (i.e. NOT being created
    this run), compare its declared columns against the columns fetched from UC
    and return any columns that should be added via ALTER TABLE ADD COLUMN.

    Logs ``NonexistentSecurableError(COLUMN, ...)`` for missing columns that
    can't be created (namespace out of creation scope, or in scope but column
    lacks ``data_type``). Opted-in out-of-scope warnings are returned as typed
    identities for downstream pruning; invalid in-scope columns remain errors.
    Columns present in actual but absent from desired are ignored — additive only.
    """
    actual_tables_by_name = {s.full_name: s for s in actual if isinstance(s, Table)}

    columns_to_create: list[Column] = []
    nonexistent_columns: set[SecurableKey] = set()
    for desired_sec in desired:
        if not isinstance(desired_sec, Table):
            continue
        if desired_sec.full_name in table_full_names_being_created:
            continue  # the CREATE TABLE path handles its columns
        actual_table = actual_tables_by_name.get(desired_sec.full_name)
        if actual_table is None:
            continue  # missing-table error is handled separately
        actual_column_names = {c.full_name for c in actual_table.columns}

        for col in desired_sec.columns:
            if col.full_name in actual_column_names:
                continue  # already exists in UC

            if creation_in_scope_namespaces.matches(col.full_name):
                blocker = _column_creation_blocker(col)
                if blocker is None:
                    columns_to_create.append(col)
                    continue
                change_logger.log_error(
                    ExecutionError(
                        context=f"Validate ADD COLUMN {col.full_name}",
                        exception=NonexistentSecurableError(
                            SecurableType.COLUMN,
                            col.full_name,
                            hint=blocker,
                        ),
                    )
                )
            else:
                error = ExecutionError(
                    context=(
                        f"Skip changes targeting nonexistent COLUMN {col.full_name}"
                        if warn_on_nonexistent_securables
                        else f"Existence check: COLUMN {col.full_name}"
                    ),
                    exception=NonexistentSecurableError(
                        SecurableType.COLUMN,
                        col.full_name,
                    ),
                )
                if warn_on_nonexistent_securables:
                    change_logger.log_warning(error)
                    nonexistent_columns.add((SecurableType.COLUMN, col.full_name))
                else:
                    change_logger.log_error(error)

    return columns_to_create, frozenset(nonexistent_columns)


def _partition_by_creation_scope(
    to_create: list[Securable],
    in_scope_namespaces: Scope,
) -> tuple[list[Securable], list[Securable]]:
    """Split ``to_create`` into (creatable, blocked).

    Functions are always creatable — they're engine-managed and exempt from
    the namespace-scope gate. Other securables (catalogs, schemas, tables,
    volumes) are creatable only if their namespace is in ``in_scope_namespaces``.
    """
    creatable: list[Securable] = []
    blocked: list[Securable] = []
    for sec in to_create:
        if isinstance(sec, Function) or in_scope_namespaces.matches(sec.full_name):
            creatable.append(sec)
        else:
            blocked.append(sec)
    return creatable, blocked


def _validate_tables_for_creation(
    to_create: list[Securable],
    change_logger: ChangeLogger,
) -> list[Securable]:
    """Validate each Table in ``to_create`` and log errors for invalid ones.

    Non-Table securables pass through unchanged — with ``--securable-creation-scopes``
    on, catalogs, schemas, volumes, and valid tables all flow to the executor.
    Tables missing columns or column types are logged as ``NonexistentSecurableError``
    (with a hint explaining the requirement) so the orchestrator's end-of-run
    ``ExecutionBatchError`` gate picks them up alongside any other errors.
    """
    kept: list[Securable] = []
    for sec in to_create:
        if isinstance(sec, Table):
            reason = _table_creation_blocker(sec)
            if reason is not None:
                change_logger.log_error(
                    ExecutionError(
                        context=f"Validate CREATE TABLE {sec.full_name}",
                        exception=NonexistentSecurableError(
                            sec.securable_type,
                            sec.full_name,
                            hint=reason,
                        ),
                    )
                )
                continue
        kept.append(sec)
    return kept


def _log_nonexistent_non_function_securables(
    to_create: list[Securable],
    change_logger: ChangeLogger,
    warn_on_nonexistent_securables: bool,
) -> frozenset[SecurableKey]:
    """Log one ``NonexistentSecurableError`` per absent non-function securable.

    The caller has already separated functions and securables within creation scope,
    so every item here is an absent object that the run cannot create. The default
    remains fatal. Opt-in warning mode returns the typed identities so the
    orchestrator can discard dependent changes across every diff domain.
    """
    nonexistent = sorted(
        [s for s in to_create if not isinstance(s, Function)],
        key=lambda s: (s.securable_type.value, s.full_name),
    )
    for sec in nonexistent:
        error = ExecutionError(
            context=(
                "Skip changes targeting nonexistent "
                f"{sec.securable_type.value} {sec.full_name}"
                if warn_on_nonexistent_securables
                else f"Existence check: {sec.securable_type.value} {sec.full_name}"
            ),
            exception=NonexistentSecurableError(sec.securable_type, sec.full_name),
        )
        if warn_on_nonexistent_securables:
            change_logger.log_warning(error)
        else:
            change_logger.log_error(error)
    if not warn_on_nonexistent_securables:
        return frozenset()
    return frozenset((sec.securable_type, sec.full_name) for sec in nonexistent)


def _data_classification_config_will_exist(
    desired: SecurableAttributes, actual: SecurableAttributes | None
) -> bool:
    """Return whether the catalog will have a Data Classification config after the
    run: it is (effectively) enabled in config, or unmanaged and already enabled."""
    if desired.data_classification_enabled is not None:
        return desired.data_classification_enabled
    return actual is not None and actual.data_classification_enabled is True


def _diff_attributes(
    desired_attrs: set[SecurableAttributes],
    actual_attrs: set[SecurableAttributes],
    created_full_names: set[str],
    view_full_names: set[str],
    owner_immutable_full_names: set[str],
    change_logger: ChangeLogger,
) -> list[AttributeUpdate]:
    """Return attribute updates by comparing desired vs actual attributes.

    Per-attribute rules:

    - ``owner`` — emitted as an SDK update even for newly-created securables
      (UC CREATE does not accept an owner). Refused for tables whose
      ``table_type`` is ``MATERIALIZED_VIEW`` or ``STREAMING_TABLE`` (the SDK
      ``tables.update(owner=...)`` path does not support them); logged as an
      ``ExecutionError`` and dropped.
    - ``comment`` — skipped for newly-created securables because the executor
      embeds the comment in the CREATE statement. For existing securables,
      comment on a view (``Table.table_type`` in ``_COMMENT_IMMUTABLE_TABLE_TYPES``)
      is refused — UC doesn't support ``COMMENT ON`` for views via this path;
      logged as an ``ExecutionError`` and dropped. Comments on other types flow
      through as ALTER updates.

    - ``data_classification_enabled`` — catalog-only. Emitted for newly-created
      catalogs too (the Data Classification config can only be created once the
      catalog exists); the fetch supplies a ``False`` baseline for such catalogs, so
      a desired ``False`` on a new catalog produces no update.
    - ``data_classification_excluded_schemas`` — catalog-only and authoritative
      (the whole set is replaced). Like ``data_classification_enabled``, emitted
      for newly-created catalogs against the fetch's empty baseline.
    - ``data_classification_included_schemas`` — catalog-only; always desired
      empty under an enabled catalog, so an include list set outside config is
      cleared (it is mutually exclusive with exclusions).
    - ``data_classification_auto_tagging_tags`` — catalog-only and authoritative.
      Dropped when the catalog will have no Data Classification config after the
      run (see ``_data_classification_config_will_exist``): auto-tagging is then
      off anyway, and there is no config to patch.

    ``location`` is creation-only (see ``compile_desired_securables``) and is
    not in ``_GOVERNED_ATTRIBUTES`` — it's never diffed.

    For resolved Principals, equality uses dataclass field equality — two
    resolved principals with the same identifier + name + type compare equal.

    Desired-only attributes are skipped unless the securable is being created.
    """
    actual_by_key = {(a.securable_type, a.full_name): a for a in actual_attrs}

    updates: list[AttributeUpdate] = []

    for desired in desired_attrs:
        key = (desired.securable_type, desired.full_name)
        actual = actual_by_key.get(key)

        if actual is None and desired.full_name not in created_full_names:
            continue

        is_being_created = desired.full_name in created_full_names

        for attr in _GOVERNED_ATTRIBUTES:
            desired_raw = getattr(desired, attr)
            if desired_raw is None:
                continue
            if attr == "data_classification_auto_tagging_tags" and not (
                _data_classification_config_will_exist(desired, actual)
            ):
                continue

            actual_raw = getattr(actual, attr, None) if actual is not None else None
            new_value = _to_frozenset(attr, desired_raw)
            old_value = _to_frozenset(attr, actual_raw)
            if old_value == new_value:
                continue

            update = AttributeUpdate(
                securable_type=desired.securable_type,
                full_name=desired.full_name,
                attribute=attr,
                old_value=old_value,
                new_value=new_value,
            )

            if _should_skip_or_log(
                update,
                is_being_created,
                view_full_names,
                owner_immutable_full_names,
                change_logger,
            ):
                continue
            updates.append(update)

    return updates


def _should_skip_or_log(
    update: AttributeUpdate,
    is_being_created: bool,
    view_full_names: set[str],
    owner_immutable_full_names: set[str],
    change_logger: ChangeLogger,
) -> bool:
    """Return True if the update should be dropped (skipped silently or after logging).

    ``comment`` updates on a securable that's being created this run are dropped
    silently — the CREATE statement embeds the comment. For existing securables,
    the view-comment and immutable-owner rules log an error before dropping.
    """
    if is_being_created and update.attribute == "comment":
        return True

    if update.attribute == "comment" and update.full_name in view_full_names:
        change_logger.log_error(
            ExecutionError(
                context=f"Update comment on {update.securable_type.value} {update.full_name}",
                exception=OrchestratorError(
                    "Cannot alter comment on a VIEW — only the view owner can alter comment."
                ),
            )
        )
        return True

    if update.attribute == "owner" and update.full_name in owner_immutable_full_names:
        change_logger.log_error(
            ExecutionError(
                context=f"Update owner on {update.securable_type.value} {update.full_name}",
                exception=OrchestratorError(
                    "Materialized views and streaming tables do not support owner "
                    "changes via this engine. Change ownership of the pipeline instead."
                ),
            )
        )
        return True

    return False
