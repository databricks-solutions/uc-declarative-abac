from __future__ import annotations

from uc_abac.configs import (
    RLS_WILDCARD,
    ColumnConfig,
    ConditionRuleConfig,
    FilterRuleConfig,
    FunctionConfig,
    ResourcesConfig,
    RlsMappingRuleConfig,
    SecurableConfig,
    TableConfig,
    render_rls_key_literal,
    rls_comparison_type,
)
from uc_abac.principals import Principal
from uc_abac.securables.state import (
    Column,
    ConditionRule,
    FilterRule,
    FilterRules,
    Function,
    RlsMappingRule,
    Securable,
    SecurableAttributes,
    Table,
)
from uc_abac.types import (
    PrincipalType,
    SecurableType,
)


def _emit_attributes(
    securable_type: SecurableType,
    obj: SecurableConfig,
) -> SecurableAttributes | None:
    """Return a SecurableAttributes if any managed (updatable) attribute is set, else None.

    Managed attributes: ``owner``, ``comment``, and ``rfa_destinations``. Owner is
    emitted as an unresolved Principal (principal_type=UNKNOWN) carrying the
    display name from config; resolution happens post-fetch. ``comment`` is read
    directly from the config and only applies to the four taggable types
    (catalogs, schemas, tables, volumes); for functions only ``owner`` and
    ``rfa_destinations`` are emitted here (the function's comment lives on the
    ``Function`` securable itself since it's part of the replaceable definition).
    ``rfa_destinations`` is stored as a frozenset (order-insensitive); the
    Pydantic validator has already classified every entry, so no further
    validation is needed here. An absent field stays ``None`` (unmanaged —
    existing destinations are left untouched), while an explicitly-empty list
    compiles to an empty frozenset, signalling "remove all destinations".

    ``location`` is **not** a managed attribute — it's only consulted at CREATE
    time (see ``compile_desired_securables``), never diffed.
    """
    owner = (
        Principal(principal_type=PrincipalType.UNKNOWN, name=obj.owner)
        if obj.owner
        else None
    )
    if securable_type == SecurableType.FUNCTION:
        comment = None
    else:
        comment = getattr(obj, "comment", None)

    raw_rfa = getattr(obj, "rfa_destinations", None)
    rfa_destinations = frozenset(raw_rfa) if raw_rfa is not None else None

    if owner is None and comment is None and rfa_destinations is None:
        return None
    return SecurableAttributes(
        securable_type=securable_type,
        full_name=obj.full_name,
        owner=owner,
        comment=comment,
        rfa_destinations=rfa_destinations,
    )


def compile_desired_attributes(config: ResourcesConfig) -> set[SecurableAttributes]:
    """Walk the config tree and emit SecurableAttributes for each securable with managed attributes."""
    attrs: set[SecurableAttributes] = set()

    for catalog in config.catalogs.values():
        if (attr := _emit_attributes(SecurableType.CATALOG, catalog)) is not None:
            attrs.add(attr)

        for schema in catalog.schemas or []:
            if (attr := _emit_attributes(SecurableType.SCHEMA, schema)) is not None:
                attrs.add(attr)

            for table in schema.tables or []:
                if (attr := _emit_attributes(SecurableType.TABLE, table)) is not None:
                    attrs.add(attr)

                for column in table.columns or []:
                    if (
                        attr := _emit_attributes(SecurableType.COLUMN, column)
                    ) is not None:
                        attrs.add(attr)

            for volume in schema.volumes or []:
                if (attr := _emit_attributes(SecurableType.VOLUME, volume)) is not None:
                    attrs.add(attr)

            for func in schema.functions or []:
                if (attr := _emit_attributes(SecurableType.FUNCTION, func)) is not None:
                    attrs.add(attr)

    return attrs


def _compile_rls_principals(names: list[str]) -> tuple[Principal, ...]:
    """Build unresolved Principals from an ``rls_mapping`` value's names, in order."""
    return tuple(
        Principal(principal_type=PrincipalType.UNKNOWN, name=name) for name in names
    )


def _compile_rls_literal(
    key: object, rule: RlsMappingRuleConfig, parameter_types: dict[str, str]
) -> str | None:
    """Render an ``rls_mapping`` key as a SQL literal of the rule's comparison type,
    or ``None`` for the ``'*'`` wildcard.

    The parameter type is only looked up for non-wildcard keys: a rule with no
    ``parameter`` is valid only when every key is a wildcard. Config validation
    has already checked every key, so rendering can't fail here.
    """
    if key == RLS_WILDCARD:
        return None
    comparison_type = rls_comparison_type(
        rule.operator, parameter_types[rule.parameter]
    )
    return render_rls_key_literal(key, comparison_type)


def _compile_rls_rule(
    rule: RlsMappingRuleConfig, parameter_types: dict[str, str]
) -> RlsMappingRule:
    """Build an RlsMappingRule whose entries follow the mapping's order."""
    entries = tuple(
        (
            _compile_rls_literal(key, rule, parameter_types),
            _compile_rls_principals(value),
        )
        for key, value in rule.rls_mapping.items()
    )
    return RlsMappingRule(
        name=rule.name,
        parameter=rule.parameter,
        operator=rule.operator,
        identity=rule.identity,
        entries=entries,
    )


def _compile_filter_rule(
    rule: FilterRuleConfig, parameter_types: dict[str, str]
) -> FilterRule:
    """Build the state rule for a condition or rls_mapping rule config."""
    if isinstance(rule, ConditionRuleConfig):
        return ConditionRule(name=rule.name, condition=rule.condition)
    return _compile_rls_rule(rule, parameter_types)


def _compile_filter_rules(func: FunctionConfig) -> FilterRules:
    """Build FilterRules from ``match_rules`` (``all_of``) and ``match_any_of_rules``
    (``any_of``), each in list order."""
    parameter_types = {p.name: p.data_type for p in func.parameters or []}
    return FilterRules(
        all_of=tuple(
            _compile_filter_rule(r, parameter_types) for r in func.match_rules or []
        ),
        any_of=tuple(
            _compile_filter_rule(r, parameter_types)
            for r in func.match_any_of_rules or []
        ),
    )


def _compile_function(func: FunctionConfig) -> Function:
    """Build a Function from a FunctionConfig.

    A function defined by filter rules gets an empty ``definition`` and a
    ``FilterRules`` spec with unresolved principals; the differ resolves them and
    renders the body. A ``return`` function carries its definition as-is.
    """
    parameters = (
        tuple((param.name, param.data_type) for param in func.parameters)
        if func.parameters
        else ()
    )
    filter_rules = _compile_filter_rules(func) if func.has_filter_rules else None
    return Function(
        securable_type=SecurableType.FUNCTION,
        full_name=func.full_name,
        parameters=parameters,
        definition=func.definition or "",
        comment=func.comment,
        filter_rules=filter_rules,
    )


def _compile_column(col: ColumnConfig) -> Column:
    """Build a Column from a ColumnConfig, preserving the optional UC datatype and comment.

    ``comment`` rides along so the executor can embed it in the CREATE TABLE /
    ALTER TABLE ADD COLUMNS statement when the column is created this run.
    """
    return Column(
        securable_type=SecurableType.COLUMN,
        full_name=col.full_name,
        data_type=col.data_type,
        comment=col.comment,
    )


def _compile_table(table: TableConfig) -> Table:
    """Build a Table with its declared columns in YAML declaration order.

    ``comment`` and ``location`` are plumbed onto the Table so the executor
    can embed them in the CREATE TABLE statement (LOCATION makes the table
    external).
    """
    return Table(
        securable_type=SecurableType.TABLE,
        full_name=table.full_name,
        columns=tuple(_compile_column(c) for c in (table.columns or [])),
        comment=table.comment,
        location=table.location,
    )


def compile_desired_securables(config: ResourcesConfig) -> set[Securable]:
    """Walk the config tree and emit a Securable for every declared securable.

    Catalogs, schemas, and volumes are emitted as base ``Securable`` instances
    carrying ``comment`` and ``location`` for the executor to embed in CREATE
    statements (``MANAGED LOCATION`` for catalogs/schemas, ``LOCATION`` for
    external tables, ``CREATE EXTERNAL VOLUME … LOCATION`` for external volumes).
    Tables are emitted as ``Table`` subclass instances carrying their declared
    columns plus ``comment`` / ``location``. Functions are emitted as
    ``Function`` instances carrying their parameters, definition, and optional
    comment so the differ can detect replacement.

    ``location`` is creation-only — the differ does not diff or alter it,
    matching the shape of ``Column.data_type``.
    """
    securables: set[Securable] = set()

    for catalog in config.catalogs.values():
        securables.add(
            Securable(
                securable_type=SecurableType.CATALOG,
                full_name=catalog.full_name,
                comment=catalog.comment,
                location=catalog.location,
            )
        )
        for schema in catalog.schemas or []:
            securables.add(
                Securable(
                    securable_type=SecurableType.SCHEMA,
                    full_name=schema.full_name,
                    comment=schema.comment,
                    location=schema.location,
                )
            )
            for table in schema.tables or []:
                securables.add(_compile_table(table))
            for volume in schema.volumes or []:
                securables.add(
                    Securable(
                        securable_type=SecurableType.VOLUME,
                        full_name=volume.full_name,
                        comment=volume.comment,
                        location=volume.location,
                    )
                )
            for func in schema.functions or []:
                securables.add(_compile_function(func))

    return securables
