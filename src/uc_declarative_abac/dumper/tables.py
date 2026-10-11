"""Snapshot table specs for ``uc-abac dump``.

Each ``TableSpec`` describes one table written into the target schema: its name, its
table comment, its ordered columns (name, SQL type, column comment), and a ``rows``
function that projects an ``ActualState`` into that table's rows.

Table shapes follow the Databricks system tables (``information_schema.*``,
``system.access.principals_latest`` / ``parent_groups_latest``) rather than the
engine's internal state classes; columns beyond the base system table are API-compatible
extensions and say so in their comment. Only state the full fetch actually populates is
written, so consumers join to the system tables for any further metadata.

Each row's ``config_file_path`` column links the row back to the uc-abac config file
that declares the corresponding object: the YAML file path from the config's
``file_path`` attribute, or NULL when the object is not in config. For privileges,
the path is attributed to the first active grant policy in config that produces the
privilege (using the actual tags in state to match). Column tags without a column
config fall back to their parent table's file path. The pseudo_policies table is read
from config grant policies (not Unity Catalog state).

Securable path columns follow the ``information_schema`` convention: ``securable_name``
is the object's own name, and ``catalog_name`` / ``schema_name`` / ``table_name`` are set
for the object and its descendants — so a column tag carries its parent table in
``table_name``, while volumes and functions leave ``table_name`` NULL. ``securables``
has no column rows (a table's columns are an array on its row, since columns can vastly
outnumber every other securable), so it drops ``table_name``.
``abac_policies`` follows the same convention for the securable a policy is attached
to (so a schema-level policy's ``securable_name`` is the schema), whereas
``abac_policy_definitions`` leaves ``securable_name`` NULL for catalog/schema-level
policies; it also has no ``table_name``, since a policy's securable is never a column.

Principal-valued columns hold canonical identifiers (username, group display name, or
service principal application id), matching the system tables.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from uc_declarative_abac.configs import (
    GrantPolicyConfig,
    ResourcesConfig,
    iter_policy_configs,
)
from uc_declarative_abac.dumper.attribution import ConfigPaths, build_config_paths
from uc_declarative_abac.governed_tags import GovernedTag, collect_referenced_tag_keys
from uc_declarative_abac.orchestrator import ActualState
from uc_declarative_abac.policies import Policy, render_tag_when_condition
from uc_declarative_abac.principals import Group, Principal
from uc_declarative_abac.privileges import SecurablePrivilege, is_active_grant_policy
from uc_declarative_abac.securables import (
    Column,
    Function,
    Securable,
    SecurableAttributes,
    Table,
)
from uc_declarative_abac.types import PolicyType, PrincipalType, SecurableType
from uc_declarative_abac.utils import is_account_users_group

RowValue = str | int | bool | tuple[str, ...] | None
Row = dict[str, RowValue]

_REPLACED_NOTE = "Fully replaced by every uc-abac dump run."
_EXTENSION_NOTE = "Extension: not in the base system table."
_IDENTIFIER_NOTE = "by canonical identifier (username, group name, or service principal application ID)"

TARGET_SCHEMA_COMMENT = (
    "Snapshot tables written by uc-abac dump: the current Unity Catalog and account "
    "state behind a uc-abac declarative ABAC config (securables, tags, privileges, "
    "policies, governed tags, domains, principals, and group memberships). Every "
    "table is fully replaced by each uc-abac dump run; see each table's comment for "
    "its grain and source. Each table's config_file_path column links rows back to the "
    "uc-abac config file that declares them."
)


@dataclass(frozen=True)
class ColumnSpec:
    """One column of a dump table: its name, Databricks SQL type, and comment."""

    name: str
    sql_type: str
    comment: str


@dataclass(frozen=True)
class DumpContext:
    """Lookups shared by the table row builders.

    ``principals_by_identifier`` maps a canonical identifier to its resolved principal,
    so identifier-only principals (group members, assumers, grantees) can be given a
    type, display name, and internal id. ``referenced_tag_keys`` is the set of governed
    tag keys the config references — the only tags whose assigners were fetched. ``config_paths`` maps each state object (securable, policy, privilege, etc.)
    back to its config file path. ``grant_policies`` holds the active grant policy configs,
    in config hierarchy order, used by the pseudo_policies table.
    """

    principals_by_identifier: dict[str, Principal]
    referenced_tag_keys: frozenset[str]
    config_paths: ConfigPaths
    grant_policies: tuple[GrantPolicyConfig, ...]


@dataclass(frozen=True)
class TableSpec:
    """One dump table: name, table comment, ordered columns, and row builder."""

    name: str
    comment: str
    columns: tuple[ColumnSpec, ...]
    rows: Callable[[ActualState, DumpContext], list[Row]]


def split_securable_name(
    securable_type: SecurableType, full_name: str
) -> tuple[str | None, str | None, str | None, str]:
    """Split a securable full name into ``(catalog, schema, table, securable_name)``.

    Follows the module's path convention: ``table_name`` is set for a table (itself)
    and a column (its parent table), and NULL for volumes and functions. Splitting is
    bounded by the type's depth so a column name containing dots stays intact.
    """
    if securable_type == SecurableType.CATALOG:
        return (full_name, None, None, full_name)
    if securable_type == SecurableType.SCHEMA:
        catalog, schema = full_name.split(".", 1)
        return (catalog, schema, None, schema)
    if securable_type == SecurableType.COLUMN:
        catalog, schema, table, column = full_name.split(".", 3)
        return (catalog, schema, table, column)
    catalog, schema, name = full_name.split(".", 2)
    table = name if securable_type == SecurableType.TABLE else None
    return (catalog, schema, table, name)


def build_dump_context(
    state: ActualState, config: ResourcesConfig, run_date: date
) -> DumpContext:
    """Build the shared row-builder lookups for ``state`` and its ``config``."""
    grant_policies = tuple(
        p
        for p in iter_policy_configs(config)
        if isinstance(p, GrantPolicyConfig) and is_active_grant_policy(p, run_date)
    )
    return DumpContext(
        principals_by_identifier={p.identifier: p for p in state.principals.values()},
        referenced_tag_keys=frozenset(collect_referenced_tag_keys(config)),
        config_paths=build_config_paths(config, state, run_date),
        grant_policies=grant_policies,
    )


def _sort_key(*values: RowValue) -> tuple[str, ...]:
    """A None-safe sort key, so rows are written in a stable order."""
    return tuple("" if value is None else str(value) for value in values)


def _identifiers(principals: Iterable[Principal]) -> tuple[str, ...]:
    return tuple(p.identifier for p in principals)


def _sorted_identifiers(
    principals: Iterable[Principal] | None,
) -> tuple[str, ...] | None:
    """Sorted identifiers, keeping ``None`` (not fetched / unmanaged) distinct from an
    empty set (known to be empty)."""
    if principals is None:
        return None
    return tuple(sorted(_identifiers(principals)))


def _column_name(column: Column, table: Table) -> str:
    """Return a column's name for the ``securables.columns`` array.

    The name is the column's full name minus its table's, so a dotted column name
    (allowed with Delta column mapping) stays whole, as in ``split_securable_name``.
    """
    return column.full_name.removeprefix(f"{table.full_name}.")


def _securable_comment(
    securable: Securable, attributes: SecurableAttributes | None
) -> str | None:
    """A function's comment rides on the Function itself (it is part of the replaceable
    definition); every other securable's comment is a fetched attribute."""
    if isinstance(securable, Function):
        return securable.comment
    return attributes.comment if attributes else None


def _securable_row(
    securable: Securable,
    attributes: SecurableAttributes | None,
    context: DumpContext,
) -> Row:
    catalog_name, schema_name, _, securable_name = split_securable_name(
        securable.securable_type, securable.full_name
    )
    is_table = isinstance(securable, Table)
    is_function = isinstance(securable, Function)
    owner = attributes.owner if attributes else None
    return {
        "config_file_path": context.config_paths.securable(
            securable.securable_type, securable.full_name
        ),
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "securable_name": securable_name,
        "securable_type": securable.securable_type.value,
        "owner": owner.identifier if owner else None,
        "comment": _securable_comment(securable, attributes),
        "table_type": securable.table_type if is_table else None,
        "columns": tuple(_column_name(c, securable) for c in securable.columns)
        if is_table
        else None,
        "routine_definition": securable.definition if is_function else None,
        "parameters": tuple(f"{name} {dtype}" for name, dtype in securable.parameters)
        if is_function
        else None,
    }


def _securables_rows(state: ActualState, context: DumpContext) -> list[Row]:
    attributes = {(a.securable_type, a.full_name): a for a in state.attributes}
    rows = [
        _securable_row(s, attributes.get((s.securable_type, s.full_name)), context)
        for s in state.securables
    ]
    return sorted(
        rows,
        key=lambda r: _sort_key(
            r["catalog_name"],
            r["schema_name"],
            r["securable_name"],
            r["securable_type"],
        ),
    )


def _securable_tags_rows(state: ActualState, context: DumpContext) -> list[Row]:
    rows: list[Row] = []
    for tag in state.tags:
        catalog_name, schema_name, table_name, securable_name = split_securable_name(
            tag.securable_type, tag.securable_full_name
        )
        config_path = context.config_paths.securable(
            tag.securable_type, tag.securable_full_name
        )
        if config_path is None and tag.securable_type == SecurableType.COLUMN:
            parent_table_name = f"{catalog_name}.{schema_name}.{table_name}"
            config_path = context.config_paths.securable(
                SecurableType.TABLE, parent_table_name
            )
        rows.append(
            {
                "config_file_path": config_path,
                "catalog_name": catalog_name,
                "schema_name": schema_name,
                "table_name": table_name,
                "securable_name": securable_name,
                "securable_type": tag.securable_type.value,
                "tag_name": tag.tag_name,
                "tag_value": tag.tag_value,
            }
        )
    return sorted(
        rows,
        key=lambda r: _sort_key(
            r["catalog_name"],
            r["schema_name"],
            r["table_name"],
            r["securable_name"],
            r["securable_type"],
            r["tag_name"],
        ),
    )


def _privilege_name(value: str) -> str:
    """System-table spelling of a privilege, e.g. ``use_catalog`` -> ``USE CATALOG``."""
    return value.upper().replace("_", " ")


def _privilege_type_name(privilege: SecurablePrivilege) -> str:
    """System-table spelling of a privilege, e.g. ``use_catalog`` -> ``USE CATALOG``."""
    return _privilege_name(privilege.privilege_type.value)


def _principal_type_of(identifier: str, context: DumpContext) -> str | None:
    resolved = context.principals_by_identifier.get(identifier)
    return resolved.principal_type.value if resolved else None


def _resolve_principal_for_row(
    principal: Principal, context: DumpContext
) -> tuple[str | None, str, str | None]:
    """Resolve a principal to ``(id, display_name, type)`` for a row.

    An unresolvable principal is still included: ``id`` and ``type`` are None, but
    ``display_name`` is the identifier (so the relationship itself is never lost).
    Used by group_members, group_assumers, and governed_tag_assigners.
    """
    resolved = context.principals_by_identifier.get(principal.identifier)
    if resolved:
        return (resolved.internal_id, resolved.name, resolved.principal_type.value)
    return (None, principal.identifier, None)


def _securable_privileges_rows(state: ActualState, context: DumpContext) -> list[Row]:
    rows: list[Row] = []
    for privilege in state.privileges:
        catalog_name, schema_name, _, securable_name = split_securable_name(
            privilege.securable_type, privilege.securable_full_name
        )
        grantee = privilege.principal.identifier
        rows.append(
            {
                "config_file_path": context.config_paths.privilege(privilege),
                "grantee": grantee,
                "grantee_type": _principal_type_of(grantee, context),
                "catalog_name": catalog_name,
                "schema_name": schema_name,
                "securable_name": securable_name,
                "securable_type": privilege.securable_type.value,
                "privilege_type": _privilege_type_name(privilege),
            }
        )
    return sorted(
        rows,
        key=lambda r: _sort_key(
            r["catalog_name"],
            r["schema_name"],
            r["securable_name"],
            r["securable_type"],
            r["grantee"],
            r["privilege_type"],
        ),
    )


_POLICY_TYPE_NAMES = {
    PolicyType.MASK: "COLUMN_MASK",
    PolicyType.FILTER: "ROW_FILTER",
}


def _abac_policy_row(policy: Policy, context: DumpContext) -> Row:
    catalog_name, schema_name, _, securable_name = split_securable_name(
        policy.securable_type, policy.securable_full_name
    )
    return {
        "config_file_path": context.config_paths.policy(
            policy.securable_type, policy.securable_full_name, policy.name
        ),
        "policy_name": policy.name,
        "policy_type": _POLICY_TYPE_NAMES[policy.policy_type],
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "securable_name": securable_name,
        "on_securable_type": policy.securable_type.value,
        "to_principals": _identifiers(policy.to_principals),
        "except_principals": _identifiers(policy.except_principals),
        "for_securable_type": policy.for_securable_type.value,
        "privileges": None,
        "when_condition": policy.when_condition,
        "match_columns": tuple(
            f"{condition} AS {alias}" for alias, condition in policy.match_columns
        ),
        "function_full_name": policy.function_name,
        "on_column": policy.on_column,
        "using_columns": tuple(policy.using_columns),
        "comment": policy.comment,
    }


def _sort_policy_rows(rows: list[Row]) -> list[Row]:
    """Shared ordering for abac_policies and pseudo_policies rows."""
    return sorted(
        rows,
        key=lambda r: _sort_key(
            r["catalog_name"], r["schema_name"], r["securable_name"], r["policy_name"]
        ),
    )


def _abac_policies_rows(state: ActualState, context: DumpContext) -> list[Row]:
    rows = [_abac_policy_row(policy, context) for policy in state.policies]
    return _sort_policy_rows(rows)


def _pseudo_policy_row(
    policy: GrantPolicyConfig, principals: dict[str, Principal]
) -> Row:
    """One pseudo_policies row; config display names in ``to`` are written as
    canonical identifiers via ``principals`` (keyed by display name), or as-is when
    they don't resolve."""
    attached_type = policy.parent_securable_type
    catalog_name, schema_name, _, securable_name = split_securable_name(
        attached_type, policy.parent_full_name
    )
    to_principals = tuple(
        principal.identifier if (principal := principals.get(name)) else name
        for name in policy.to
    )
    return {
        "config_file_path": policy.file_path.as_posix() if policy.file_path else None,
        "policy_name": policy.name,
        "policy_type": "GRANT",
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "securable_name": securable_name,
        "on_securable_type": attached_type.value,
        "to_principals": to_principals,
        "except_principals": None,
        "for_securable_type": policy.for_securable_type.value
        if policy.for_securable_type
        else None,
        "privileges": tuple(_privilege_name(p.value) for p in policy.privileges),
        "when_condition": render_tag_when_condition(
            policy.has_tags, policy.has_any_of_tags
        ),
        "match_columns": None,
        "function_full_name": None,
        "on_column": None,
        "using_columns": None,
        "comment": policy.comment,
    }


def _pseudo_policies_rows(state: ActualState, context: DumpContext) -> list[Row]:
    """One row per active grant policy, in declared order, from config.

    Grant policies are expanded into concrete privileges (in securable_privileges)
    rather than deployed as UC ABAC policies, so this table is read from config.
    Only active (unexpired) grants are included. Columns reserved for mask/filter
    policies (match_columns, function_full_name, on_column, using_columns, and
    except_principals) are NULL.
    """
    rows = [
        _pseudo_policy_row(policy, state.principals)
        for policy in context.grant_policies
    ]
    return _sort_policy_rows(rows)


def _governed_tag_assigner_row(
    tag: GovernedTag, assigner: Principal, context: DumpContext
) -> Row:
    assigner_id, display_name, assigner_type = _resolve_principal_for_row(
        assigner, context
    )
    return {
        "config_file_path": context.config_paths.governed_tag(tag.name),
        "assigner_id": assigner_id,
        "tag_key": tag.name,
        "assigner_display_name": display_name,
        "assigner_type": assigner_type,
    }


def _governed_tag_assigners_rows(state: ActualState, context: DumpContext) -> list[Row]:
    """One row per (governed tag, assigner) for tags the config references.

    Assigners are only fetched for tags in ``context.referenced_tag_keys``, so an
    unreferenced tag's assigners are unknown and yield no rows.
    """
    rows = [
        _governed_tag_assigner_row(tag, assigner, context)
        for tag in state.governed_tags
        if tag.name in context.referenced_tag_keys
        for assigner in tag.assigners
    ]
    return sorted(
        rows, key=lambda r: _sort_key(r["tag_key"], r["assigner_display_name"])
    )


def _governed_tags_rows(state: ActualState, context: DumpContext) -> list[Row]:
    rows: list[Row] = [
        {
            "config_file_path": context.config_paths.governed_tag(tag.name),
            "tag_key": tag.name,
            "description": tag.description or None,
            "values": tuple(sorted(tag.allowed_values)),
        }
        for tag in state.governed_tags
    ]
    return sorted(rows, key=lambda r: _sort_key(r["tag_key"]))


def _domains_rows(state: ActualState, context: DumpContext) -> list[Row]:
    rows: list[Row] = [
        {
            "config_file_path": context.config_paths.domain(domain.tag_key),
            "tag_key": domain.tag_key,
            "description": domain.description or None,
            "subtitle": domain.subtitle,
            "draft": domain.draft,
            "icon_name": (domain.icon.name or None) if domain.icon else None,
            "icon_color": (domain.icon.color or None) if domain.icon else None,
            "business_owners": _sorted_identifiers(domain.business_owners),
            "technical_owners": _sorted_identifiers(domain.technical_owners),
            "parent_tag_key": domain.parent_tag_key or None,
        }
        for domain in state.domains
    ]
    return sorted(rows, key=lambda r: _sort_key(r["tag_key"]))


def _principal_config_path(principal: Principal, context: DumpContext) -> str | None:
    """Only groups are declared in config; a group's configured ``id`` is its
    internal id, so it matches even after an account-side rename."""
    if principal.principal_type != PrincipalType.GROUP:
        return None
    return context.config_paths.group(principal.name, principal.internal_id)


def _principals_rows(state: ActualState, context: DumpContext) -> list[Row]:
    rows: list[Row] = [
        {
            "config_file_path": _principal_config_path(p, context),
            "principal_id": p.internal_id,
            "principal_type": p.principal_type.value,
            "display_name": p.name,
            "email": p.identifier if p.principal_type == PrincipalType.USER else None,
            "application_id": p.identifier
            if p.principal_type == PrincipalType.SERVICE_PRINCIPAL
            else None,
        }
        for p in state.principals.values()
    ]
    return sorted(rows, key=lambda r: _sort_key(r["principal_type"], r["display_name"]))


def _group_principal_row(
    group: Group, principal: Principal, prefix: str, context: DumpContext
) -> Row:
    """One group/principal pair.

    An unresolvable principal is still written, keyed by its identifier, so the
    membership itself is never lost.
    """
    principal_id, display_name, principal_type = _resolve_principal_for_row(
        principal, context
    )
    return {
        "config_file_path": context.config_paths.group(
            group.display_name, group.id or None
        ),
        f"{prefix}_id": principal_id,
        "group_id": group.id or None,
        "group_display_name": group.display_name,
        f"{prefix}_display_name": display_name,
        f"{prefix}_type": principal_type,
    }


def _group_pair_rows(
    state: ActualState,
    context: DumpContext,
    principals_of: Callable[[Group], frozenset[Principal] | None],
    prefix: str,
) -> list[Row]:
    """Pair-grain rows for ``state.groups`` (the config-referenced groups, the only
    ones whose members/assumers were fetched). ``account users`` is never written, and
    a group whose principals weren't fetched (``None``) yields no rows."""
    rows = [
        _group_principal_row(group, principal, prefix, context)
        for group in state.groups
        if not is_account_users_group(group.display_name)
        for principal in principals_of(group) or ()
    ]
    return sorted(
        rows,
        key=lambda r: _sort_key(r["group_display_name"], r[f"{prefix}_display_name"]),
    )


def _group_members_rows(state: ActualState, context: DumpContext) -> list[Row]:
    return _group_pair_rows(state, context, lambda g: g.members, "member")


def _group_assumers_rows(state: ActualState, context: DumpContext) -> list[Row]:
    return _group_pair_rows(state, context, lambda g: g.assumers, "assumer")


_CONFIG_FILE_PATH = ColumnSpec(
    "config_file_path",
    "STRING",
    "YAML file in the uc-abac config that declares this row's object (for a "
    "privilege, the first active grant policy that produces it; for a tag on an "
    "undeclared column, the column's table). NULL when the object is not in the "
    f"config. {_EXTENSION_NOTE}",
)

_CATALOG_NAME = ColumnSpec(
    "catalog_name",
    "STRING",
    "Catalog containing the securable (for a catalog row, the catalog itself).",
)
_SCHEMA_NAME = ColumnSpec(
    "schema_name",
    "STRING",
    "Schema containing the securable (for a schema row, the schema itself). "
    "NULL for catalogs.",
)
_TABLE_NAME = ColumnSpec(
    "table_name",
    "STRING",
    "Table containing the securable (for a table row, the table itself; for a column "
    "row, its parent table). NULL for catalogs, schemas, volumes, and functions.",
)
_SECURABLE_NAME = ColumnSpec(
    "securable_name",
    "STRING",
    "The securable's own name: the catalog, schema, table, column, volume, or "
    "function name.",
)
_SECURABLE_TYPE = ColumnSpec(
    "securable_type",
    "STRING",
    "Securable type: CATALOG, SCHEMA, TABLE, COLUMN, VOLUME, or FUNCTION. "
    f"{_EXTENSION_NOTE}",
)

_POLICY_COLUMNS: tuple[ColumnSpec, ...] = (
    _CONFIG_FILE_PATH,
    ColumnSpec("policy_name", "STRING", "Name of the policy."),
    ColumnSpec(
        "policy_type",
        "STRING",
        "ROW_FILTER or COLUMN_MASK in abac_policies; GRANT in pseudo_policies.",
    ),
    ColumnSpec(
        "catalog_name",
        "STRING",
        "Catalog the policy is attached to, or that contains the securable it "
        "is attached to.",
    ),
    ColumnSpec(
        "schema_name",
        "STRING",
        "Schema the policy is attached to, or that contains the table it is "
        "attached to. NULL for catalog-level policies.",
    ),
    ColumnSpec(
        "securable_name",
        "STRING",
        "Name of the securable the policy is attached to: the catalog, schema, "
        "or table name. Differs from abac_policy_definitions, which leaves it "
        "NULL for catalog- and schema-level policies.",
    ),
    ColumnSpec(
        "on_securable_type",
        "STRING",
        "Type of securable the policy is attached to: CATALOG, SCHEMA, or TABLE.",
    ),
    ColumnSpec(
        "to_principals",
        "ARRAY<STRING>",
        f"Principals the policy applies to, {_IDENTIFIER_NOTE}.",
    ),
    ColumnSpec(
        "except_principals",
        "ARRAY<STRING>",
        f"Principals exempted from the policy, {_IDENTIFIER_NOTE}. NULL for grant "
        "policies.",
    ),
    ColumnSpec(
        "for_securable_type",
        "STRING",
        "Type of securable the policy applies to, e.g. TABLE. NULL for a grant policy "
        "that applies to every securable type.",
    ),
    ColumnSpec(
        "privileges",
        "ARRAY<STRING>",
        "Privileges granted, as declared, e.g. SELECT, USE CATALOG, or READ. NULL for "
        "row filters and column masks.",
    ),
    ColumnSpec(
        "when_condition",
        "STRING",
        "WHEN condition limiting the securables the policy applies to (for a grant "
        "policy, its tag predicate). NULL when the policy has none.",
    ),
    ColumnSpec(
        "match_columns",
        "ARRAY<STRING>",
        "MATCH COLUMNS conditions in order, each as '<condition> AS <alias>'. NULL "
        "for grant policies.",
    ),
    ColumnSpec(
        "function_full_name",
        "STRING",
        "Fully qualified name of the row filter or column mask function. NULL for "
        "grant policies. "
        f"{_EXTENSION_NOTE}",
    ),
    ColumnSpec(
        "on_column",
        "STRING",
        "Alias of the matched column the mask is applied to. NULL for row filters "
        f"and grant policies. {_EXTENSION_NOTE}",
    ),
    ColumnSpec(
        "using_columns",
        "ARRAY<STRING>",
        "Arguments passed to the function via USING COLUMNS, in order. NULL for "
        "grant policies. "
        f"{_EXTENSION_NOTE}",
    ),
    ColumnSpec(
        "comment",
        "STRING",
        f"Policy comment. NULL when unset. {_EXTENSION_NOTE}",
    ),
)

TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        name="securables",
        comment=(
            "Snapshot of the Unity Catalog securables declared in the uc-abac config: "
            "one row per catalog, schema, table, volume, and function, with each "
            "table's columns held in its columns array. Mirrors "
            "system.information_schema catalogs, schemata, tables, volumes, and "
            f"routines. {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            _CATALOG_NAME,
            _SCHEMA_NAME,
            _SECURABLE_NAME,
            ColumnSpec(
                "securable_type",
                "STRING",
                "Securable type: CATALOG, SCHEMA, TABLE, VOLUME, or FUNCTION. "
                f"{_EXTENSION_NOTE}",
            ),
            ColumnSpec(
                "owner",
                "STRING",
                f"Owner of the securable, {_IDENTIFIER_NOTE}.",
            ),
            ColumnSpec(
                "comment",
                "STRING",
                "Comment on the securable. NULL when unset.",
            ),
            ColumnSpec(
                "table_type",
                "STRING",
                "Table type, e.g. MANAGED, EXTERNAL, VIEW, or MATERIALIZED_VIEW. "
                "NULL for non-table rows.",
            ),
            ColumnSpec(
                "columns",
                "ARRAY<STRING>",
                "The table's column names in ordinal order. NULL for non-table rows. "
                f"{_EXTENSION_NOTE} (information_schema.columns holds these as "
                "separate rows).",
            ),
            ColumnSpec(
                "routine_definition",
                "STRING",
                "Body of the function. NULL for non-function rows.",
            ),
            ColumnSpec(
                "parameters",
                "ARRAY<STRING>",
                "Function parameters in declaration order, each as '<name> <type>'. "
                f"NULL for non-function rows. {_EXTENSION_NOTE}",
            ),
        ),
        rows=_securables_rows,
    ),
    TableSpec(
        name="securable_tags",
        comment=(
            "Snapshot of the tags assigned to securables in the uc-abac config's "
            "catalogs: one row per securable and tag. Mirrors the "
            "system.information_schema *_tags views (catalog_tags, schema_tags, "
            f"table_tags, column_tags, volume_tags). {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            _CATALOG_NAME,
            _SCHEMA_NAME,
            _TABLE_NAME,
            _SECURABLE_NAME,
            _SECURABLE_TYPE,
            ColumnSpec("tag_name", "STRING", "Tag key."),
            ColumnSpec(
                "tag_value",
                "STRING",
                "Tag value (an empty string for a key-only tag).",
            ),
        ),
        rows=_securable_tags_rows,
    ),
    TableSpec(
        name="securable_privileges",
        comment=(
            "Snapshot of the privileges granted on securables in the uc-abac config's "
            "catalogs: one row per securable, grantee, and privilege. Mirrors the "
            "system.information_schema *_privileges views. "
            f"{_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            ColumnSpec(
                "grantee",
                "STRING",
                f"Principal holding the privilege, {_IDENTIFIER_NOTE}.",
            ),
            ColumnSpec(
                "grantee_type",
                "STRING",
                "Principal type of the grantee: USER, GROUP, or SERVICE_PRINCIPAL. "
                f"NULL when the grantee could not be resolved. {_EXTENSION_NOTE}",
            ),
            _CATALOG_NAME,
            _SCHEMA_NAME,
            _SECURABLE_NAME,
            _SECURABLE_TYPE,
            ColumnSpec(
                "privilege_type",
                "STRING",
                "Privilege granted, e.g. SELECT, USE CATALOG, or ALL PRIVILEGES.",
            ),
        ),
        rows=_securable_privileges_rows,
    ),
    TableSpec(
        name="abac_policies",
        comment=(
            "Snapshot of the ABAC row filter and column mask policies attached to "
            "securables in the uc-abac config's catalogs: one row per policy. Mirrors "
            f"system.information_schema.abac_policy_definitions. {_REPLACED_NOTE}"
        ),
        columns=_POLICY_COLUMNS,
        rows=_abac_policies_rows,
    ),
    TableSpec(
        name="pseudo_policies",
        comment=(
            "The active grant policies declared in the uc-abac config, in the shape of "
            "abac_policies: one row per grant policy. Read from the config, not from "
            "Unity Catalog, since grant policies are expanded into concrete privileges "
            f"(see securable_privileges). {_REPLACED_NOTE}"
        ),
        columns=_POLICY_COLUMNS,
        rows=_pseudo_policies_rows,
    ),
    TableSpec(
        name="governed_tags",
        comment=(
            "Snapshot of the account's governed tags (tag policies): one row per tag "
            f"key. Mirrors the Tag Policies API (no system table). {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            ColumnSpec("tag_key", "STRING", "Governed tag key."),
            ColumnSpec(
                "description",
                "STRING",
                "Description of the governed tag. NULL when unset.",
            ),
            ColumnSpec(
                "values",
                "ARRAY<STRING>",
                "Allowed values, sorted. Empty when any value is allowed.",
            ),
        ),
        rows=_governed_tags_rows,
    ),
    TableSpec(
        name="governed_tag_assigners",
        comment=(
            "Snapshot of the principals permitted to assign every governed tag the "
            "uc-abac config references: one row per tag key and assigner. Mirrors the "
            "account access-control rule set API, in the shape of group_assumers (no "
            f"system table). {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            ColumnSpec(
                "assigner_id",
                "STRING",
                "Internal ID of the assigner principal; joins to "
                "principals.principal_id. NULL when unknown.",
            ),
            ColumnSpec(
                "tag_key", "STRING", "Governed tag key; joins to governed_tags.tag_key."
            ),
            ColumnSpec(
                "assigner_display_name",
                "STRING",
                "Display name of the assigner (for users, the username; the canonical "
                "identifier when the assigner could not be resolved).",
            ),
            ColumnSpec(
                "assigner_type",
                "STRING",
                "Principal type of the assigner: USER, GROUP, or SERVICE_PRINCIPAL. "
                "NULL when the assigner could not be resolved.",
            ),
        ),
        rows=_governed_tag_assigners_rows,
    ),
    TableSpec(
        name="domains",
        comment=(
            "Snapshot of the workspace's Discovery domains: one row per domain. "
            f"Mirrors the Domains API (no system table). {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            ColumnSpec(
                "tag_key", "STRING", "Governed tag key that identifies the domain."
            ),
            ColumnSpec(
                "description",
                "STRING",
                "Description of the domain. NULL when unset.",
            ),
            ColumnSpec(
                "subtitle", "STRING", "Subtitle of the domain. NULL when unset."
            ),
            ColumnSpec(
                "draft",
                "BOOLEAN",
                "Whether the domain is a draft. NULL when unknown.",
            ),
            ColumnSpec(
                "icon_name", "STRING", "Name of the domain's icon. NULL when unset."
            ),
            ColumnSpec(
                "icon_color",
                "STRING",
                "Hex colour of the domain's icon. NULL when unset.",
            ),
            ColumnSpec(
                "business_owners",
                "ARRAY<STRING>",
                f"Business owners of the domain, {_IDENTIFIER_NOTE}.",
            ),
            ColumnSpec(
                "technical_owners",
                "ARRAY<STRING>",
                f"Technical owners of the domain, {_IDENTIFIER_NOTE}.",
            ),
            ColumnSpec(
                "parent_tag_key",
                "STRING",
                "Tag key of the parent domain. NULL for top-level domains.",
            ),
        ),
        rows=_domains_rows,
    ),
    TableSpec(
        name="principals",
        comment=(
            "Snapshot of the account's users, groups, and service principals: one row "
            f"per principal. Mirrors system.access.principals_latest. {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            ColumnSpec(
                "principal_id",
                "STRING",
                "Internal numeric ID of the principal. NULL when unknown, e.g. for "
                "account system groups.",
            ),
            ColumnSpec(
                "principal_type",
                "STRING",
                "Principal type: USER, GROUP, or SERVICE_PRINCIPAL.",
            ),
            ColumnSpec(
                "display_name",
                "STRING",
                "Display name of the principal (for users, the username).",
            ),
            ColumnSpec(
                "email",
                "STRING",
                "Username (email) of a user. NULL for groups and service principals.",
            ),
            ColumnSpec(
                "application_id",
                "STRING",
                "Application ID of a service principal. NULL for users and groups.",
            ),
        ),
        rows=_principals_rows,
    ),
    TableSpec(
        name="group_members",
        comment=(
            "Snapshot of the direct members of every group the uc-abac config "
            "references (except 'account users'): one row per group and direct member. "
            "Mirrors system.access.parent_groups_latest, restricted to direct "
            f"memberships. {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            ColumnSpec(
                "member_id",
                "STRING",
                "Internal ID of the member principal; joins to principals.principal_id. "
                "NULL when unknown.",
            ),
            ColumnSpec(
                "group_id",
                "STRING",
                "Internal ID of the group; joins to principals.principal_id.",
            ),
            ColumnSpec(
                "group_display_name",
                "STRING",
                f"Display name of the group. {_EXTENSION_NOTE}",
            ),
            ColumnSpec(
                "member_display_name",
                "STRING",
                "Display name of the member (for users, the username; the canonical "
                f"identifier when the member could not be resolved). {_EXTENSION_NOTE}",
            ),
            ColumnSpec(
                "member_type",
                "STRING",
                "Principal type of the member: USER, GROUP, or SERVICE_PRINCIPAL. NULL "
                f"when the member could not be resolved. {_EXTENSION_NOTE}",
            ),
        ),
        rows=_group_members_rows,
    ),
    TableSpec(
        name="group_assumers",
        comment=(
            "Snapshot of the principals permitted to assume every group the uc-abac "
            "config references (except 'account users'): one row per group and "
            "assumer. Mirrors the account access-control rule set API, in the shape of "
            f"group_members (no system table). {_REPLACED_NOTE}"
        ),
        columns=(
            _CONFIG_FILE_PATH,
            ColumnSpec(
                "assumer_id",
                "STRING",
                "Internal ID of the assumer principal; joins to "
                "principals.principal_id. NULL when unknown.",
            ),
            ColumnSpec(
                "group_id",
                "STRING",
                "Internal ID of the group; joins to principals.principal_id.",
            ),
            ColumnSpec("group_display_name", "STRING", "Display name of the group."),
            ColumnSpec(
                "assumer_display_name",
                "STRING",
                "Display name of the assumer (for users, the username; the canonical "
                "identifier when the assumer could not be resolved).",
            ),
            ColumnSpec(
                "assumer_type",
                "STRING",
                "Principal type of the assumer: USER, GROUP, or SERVICE_PRINCIPAL. "
                "NULL when the assumer could not be resolved.",
            ),
        ),
        rows=_group_assumers_rows,
    ),
)
