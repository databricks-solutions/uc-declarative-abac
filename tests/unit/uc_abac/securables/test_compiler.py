from __future__ import annotations

from datetime import date

from uc_abac.configs import ResourcesConfig
from uc_abac.principals import Principal
from uc_abac.securables import (
    Column,
    ConditionRule,
    FilterRules,
    Function,
    RlsMappingRule,
    Securable,
    SecurableAttributes,
    Table,
    compile_desired_attributes,
    compile_desired_securables,
)
from uc_abac.types import (
    PrincipalType,
    SecurableType,
)


def _unknown_owner(name: str) -> Principal:
    return Principal(principal_type=PrincipalType.UNKNOWN, name=name)


# ---------------------------------------------------------------------------
# compile_desired_attributes
# ---------------------------------------------------------------------------


def test_securable_compiler_emits_catalog_owner():
    """A catalog with owner produces a SecurableAttributes for the catalog."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "owner": "admin_user",
                }
            }
        }
    )

    result = compile_desired_attributes(config)

    assert result == {
        SecurableAttributes(
            securable_type=SecurableType.CATALOG,
            full_name="my_catalog",
            owner=_unknown_owner("admin_user"),
        )
    }


def test_securable_compiler_emits_schema_owner():
    """A schema with owner produces a SecurableAttributes with a two-part full name."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "sales",
                            "owner": "schema_owner",
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.SCHEMA,
            full_name="my_catalog.sales",
            owner=_unknown_owner("schema_owner"),
        )
        in result
    )


def test_securable_compiler_emits_table_owner():
    """A table with owner produces a SecurableAttributes with a three-part full name."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "owner": "table_owner",
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.TABLE,
            full_name="my_catalog.sales.orders",
            owner=_unknown_owner("table_owner"),
        )
        in result
    )


def test_securable_compiler_emits_volume_owner():
    """A volume with owner produces a SecurableAttributes with a three-part full name."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "landing",
                            "volumes": [
                                {
                                    "name": "files",
                                    "owner": "vol_owner",
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.VOLUME,
            full_name="my_catalog.landing.files",
            owner=_unknown_owner("vol_owner"),
        )
        in result
    )


def test_securable_compiler_emits_function_owner():
    """A function with owner produces a SecurableAttributes with a three-part full name."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [
                                {
                                    "name": "mask_email",
                                    "owner": "func_owner",
                                    "parameters": [{"name": "col", "type": "STRING"}],
                                    "return": "CASE WHEN is_member('admins') THEN col ELSE '***' END",
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.FUNCTION,
            full_name="my_catalog.shared.mask_email",
            owner=_unknown_owner("func_owner"),
        )
        in result
    )


def test_securable_compiler_skips_securables_without_managed_attributes():
    """A catalog with no owner/comment/location is not emitted in the attributes set."""
    config = ResourcesConfig.model_validate({"catalogs": {"my_catalog": {}}})

    result = compile_desired_attributes(config)

    assert result == set()


# ---------------------------------------------------------------------------
# compile_desired_attributes — comment + location
# ---------------------------------------------------------------------------


def test_securable_compiler_emits_catalog_comment_in_attributes():
    """A catalog with a comment produces a SecurableAttributes carrying it. Catalogs
    do not currently support ``location`` (managed location)."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "comment": "Prod catalog",
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.CATALOG,
            full_name="my_cat",
            owner=None,
            comment="Prod catalog",
        )
        in result
    )


def test_securable_compiler_emits_schema_comment_in_attributes():
    """A schema with a comment produces a SecurableAttributes carrying it. Schemas
    do not currently support ``location`` (managed location)."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "comment": "Sales data",
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.SCHEMA,
            full_name="my_cat.sales",
            comment="Sales data",
        )
        in result
    )


def test_securable_compiler_emits_table_comment_in_attributes():
    """A table with a comment produces a SecurableAttributes carrying it.

    ``location`` is creation-only (not part of SecurableAttributes); see
    ``test_securables_compiler_plumbs_*_onto_*_securable`` for CREATE-time plumbing.
    """
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "comment": "Orders fact",
                                    "location": "s3://ext/orders",
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.TABLE,
            full_name="my_cat.sales.orders",
            comment="Orders fact",
        )
        in result
    )


def test_securable_compiler_emits_volume_comment_in_attributes():
    """A volume with a comment produces a SecurableAttributes carrying it.

    ``location`` is creation-only (not part of SecurableAttributes).
    """
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "landing",
                            "volumes": [
                                {
                                    "name": "raw",
                                    "comment": "Raw landing",
                                    "location": "s3://ext/raw",
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.VOLUME,
            full_name="my_cat.landing.raw",
            comment="Raw landing",
        )
        in result
    )


def test_securable_compiler_emits_attributes_when_only_comment_is_set():
    """A catalog with only a comment (no owner) still produces a SecurableAttributes."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {"comment": "Just a comment"},
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.CATALOG,
            full_name="my_cat",
            comment="Just a comment",
        )
        in result
    )


def test_securable_compiler_emits_no_attributes_when_only_location_is_set():
    """A volume with only a location (no owner, no comment) does NOT produce a
    SecurableAttributes — ``location`` is creation-only and isn't tracked as a
    managed attribute."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "landing",
                            "volumes": [
                                {"name": "raw", "location": "s3://ext/raw"},
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert not any(a.securable_type == SecurableType.VOLUME for a in result)


def test_securable_compiler_does_not_emit_function_comment_into_attributes():
    """Function comments live on the Function securable itself, not on SecurableAttributes."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [
                                {
                                    "name": "mask_pii",
                                    "parameters": [{"name": "x", "type": "STRING"}],
                                    "return": "x",
                                    "comment": "Mask helper",
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    # No SecurableAttributes is emitted for the function (no owner, and we don't
    # promote function comments into the attribute path).
    assert not any(a.securable_type == SecurableType.FUNCTION for a in result)


def test_securable_compiler_emits_column_comment_in_attributes():
    """A column with a comment produces a SecurableAttributes carrying it."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "columns": [
                                        {
                                            "name": "email",
                                            "data_type": "STRING",
                                            "comment": "Customer email",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.COLUMN,
            full_name="my_cat.sales.orders.email",
            comment="Customer email",
        )
        in result
    )


def test_securable_compiler_omits_column_without_comment_from_attributes():
    """A column without a comment produces no COLUMN-typed SecurableAttributes."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "columns": [
                                        {
                                            "name": "email",
                                            "data_type": "STRING",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_attributes(config)

    # No COLUMN-typed attributes should be emitted
    assert not any(a.securable_type == SecurableType.COLUMN for a in result)


# ---------------------------------------------------------------------------
# compile_desired_attributes — rfa_destinations
# ---------------------------------------------------------------------------


# A representative mix exercising every regex-recognised RFA destination form:
# an email, an HTTPS URL, and a canonical 8-4-4-4-12 UUID.
_RFA_DESTINATIONS = [
    "data-gov@example.com",
    "https://hooks.example.com/rfa",
    "12345678-1234-1234-1234-123456789abc",
]


def test_securable_compiler_emits_catalog_rfa_destinations():
    """A catalog with rfa_destinations produces a SecurableAttributes carrying the
    destinations as a frozenset (order-insensitive)."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "rfa_destinations": list(_RFA_DESTINATIONS),
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.CATALOG,
            full_name="my_cat",
            rfa_destinations=frozenset(_RFA_DESTINATIONS),
        )
        in result
    )


def test_securable_compiler_emits_schema_rfa_destinations():
    """A schema with rfa_destinations produces a SecurableAttributes carrying them."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "rfa_destinations": list(_RFA_DESTINATIONS),
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.SCHEMA,
            full_name="my_cat.sales",
            rfa_destinations=frozenset(_RFA_DESTINATIONS),
        )
        in result
    )


def test_securable_compiler_emits_table_rfa_destinations():
    """A table with rfa_destinations produces a SecurableAttributes carrying them."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "rfa_destinations": list(_RFA_DESTINATIONS),
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.TABLE,
            full_name="my_cat.sales.orders",
            rfa_destinations=frozenset(_RFA_DESTINATIONS),
        )
        in result
    )


def test_securable_compiler_emits_volume_rfa_destinations():
    """A volume with rfa_destinations produces a SecurableAttributes carrying them."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "landing",
                            "volumes": [
                                {
                                    "name": "raw",
                                    "rfa_destinations": list(_RFA_DESTINATIONS),
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.VOLUME,
            full_name="my_cat.landing.raw",
            rfa_destinations=frozenset(_RFA_DESTINATIONS),
        )
        in result
    )


def test_securable_compiler_emits_function_rfa_destinations():
    """A function with rfa_destinations produces a SecurableAttributes carrying them."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [
                                {
                                    "name": "mask_email",
                                    "parameters": [{"name": "col", "type": "STRING"}],
                                    "return": "col",
                                    "rfa_destinations": list(_RFA_DESTINATIONS),
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.FUNCTION,
            full_name="my_cat.shared.mask_email",
            rfa_destinations=frozenset(_RFA_DESTINATIONS),
        )
        in result
    )


def test_securable_compiler_rfa_destinations_is_none_when_absent():
    """A catalog with an owner but no rfa_destinations leaves
    SecurableAttributes.rfa_destinations as None (not an empty frozenset)."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {"owner": "admin_user"},
            },
        }
    )

    result = compile_desired_attributes(config)

    catalog_attrs = next(
        a
        for a in result
        if a.securable_type == SecurableType.CATALOG and a.full_name == "my_cat"
    )
    assert catalog_attrs.rfa_destinations is None


def test_securable_compiler_emits_attributes_when_only_rfa_destinations_set():
    """A catalog with only rfa_destinations (no owner, no comment) still produces
    a SecurableAttributes — and a sibling catalog with no managed attributes at
    all does not."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "with_rfa": {
                    "rfa_destinations": list(_RFA_DESTINATIONS),
                },
                "without_anything": {},
            },
        }
    )

    result = compile_desired_attributes(config)

    assert (
        SecurableAttributes(
            securable_type=SecurableType.CATALOG,
            full_name="with_rfa",
            rfa_destinations=frozenset(_RFA_DESTINATIONS),
        )
        in result
    )
    assert not any(a.full_name == "without_anything" for a in result)


def test_securable_compiler_emits_empty_rfa_destinations_when_explicitly_empty_list():
    """A catalog with an explicitly-empty rfa_destinations list produces a
    SecurableAttributes whose rfa_destinations is an empty frozenset (not None) —
    signalling "remove all", distinct from the absent/unmanaged case. This holds
    even when no other managed attribute (owner/comment) is set."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {"rfa_destinations": []},
            },
        }
    )

    result = compile_desired_attributes(config)

    catalog_attrs = next(
        a
        for a in result
        if a.securable_type == SecurableType.CATALOG and a.full_name == "my_cat"
    )
    assert catalog_attrs.rfa_destinations == frozenset()


# ---------------------------------------------------------------------------
# compile_desired_securables
# ---------------------------------------------------------------------------


def test_securable_compiler_emits_function_info():
    """A function config produces a Function with parameters and definition."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [
                                {
                                    "name": "mask_email",
                                    "owner": "func_owner",
                                    "parameters": [{"name": "col", "type": "STRING"}],
                                    "return": "CASE WHEN is_member('admins') THEN col ELSE '***' END",
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    assert (
        Function(
            securable_type=SecurableType.FUNCTION,
            full_name="my_catalog.shared.mask_email",
            parameters=(("col", "STRING"),),
            definition="CASE WHEN is_member('admins') THEN col ELSE '***' END",
        )
        in result
    )


def test_securable_compiler_emits_function_info_without_parameters():
    """A function with no parameters produces a Function with parameters=()."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [
                                {
                                    "name": "get_greeting",
                                    "return": "'Hello, World!'",
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    assert (
        Function(
            securable_type=SecurableType.FUNCTION,
            full_name="my_catalog.shared.get_greeting",
            parameters=(),
            definition="'Hello, World!'",
        )
        in result
    )


def test_securable_compiler_emits_function_comment_when_provided():
    """FunctionConfig.comment is propagated onto the emitted Function."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [
                                {
                                    "name": "greet",
                                    "return": "'hi'",
                                    "comment": "Returns a greeting",
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)
    func = next(s for s in result if isinstance(s, Function))
    assert func.comment == "Returns a greeting"


def test_securable_compiler_function_comment_defaults_to_none():
    """A function without a comment emits Function.comment == None."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [{"name": "greet", "return": "'hi'"}],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)
    func = next(s for s in result if isinstance(s, Function))
    assert func.comment is None


# ---------------------------------------------------------------------------
# compile_desired_securables — base Securable emissions for catalog/schema/table/volume
# ---------------------------------------------------------------------------


def test_securables_compiler_emits_securable_for_each_declared_catalog():
    """Every declared catalog appears in the desired-securables set as a base Securable."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat_a": {},
                "cat_b": {},
            }
        }
    )

    result = compile_desired_securables(config)

    assert Securable(securable_type=SecurableType.CATALOG, full_name="cat_a") in result
    assert Securable(securable_type=SecurableType.CATALOG, full_name="cat_b") in result


def test_securables_compiler_emits_securable_for_each_declared_schema():
    """Every declared schema appears in the desired-securables set as a base Securable."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat": {
                    "schemas": [
                        {"name": "sales"},
                        {"name": "hr"},
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    assert (
        Securable(securable_type=SecurableType.SCHEMA, full_name="cat.sales") in result
    )
    assert Securable(securable_type=SecurableType.SCHEMA, full_name="cat.hr") in result


def test_securables_compiler_emits_table_subclass_for_each_declared_table():
    """Every declared table appears in the desired-securables set as a Table instance
    (not a base Securable) so the executor can reach columns for CREATE TABLE SQL."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {"name": "orders"},
                                {"name": "customers"},
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    assert (
        Table(
            securable_type=SecurableType.TABLE, full_name="cat.sales.orders", columns=()
        )
        in result
    )
    assert (
        Table(
            securable_type=SecurableType.TABLE,
            full_name="cat.sales.customers",
            columns=(),
        )
        in result
    )


def test_securables_compiler_emits_column_with_data_type_when_specified():
    """A declared column with a 'data_type' produces a Column with that data_type string."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "columns": [
                                        {"name": "email", "data_type": "STRING"},
                                        {
                                            "name": "amount",
                                            "data_type": "DECIMAL(18,2)",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    orders = next(
        s for s in result if isinstance(s, Table) and s.full_name == "cat.sales.orders"
    )
    assert (
        Column(
            securable_type=SecurableType.COLUMN,
            full_name="cat.sales.orders.email",
            data_type="STRING",
        )
        in orders.columns
    )
    assert (
        Column(
            securable_type=SecurableType.COLUMN,
            full_name="cat.sales.orders.amount",
            data_type="DECIMAL(18,2)",
        )
        in orders.columns
    )


def test_securables_compiler_emits_column_with_data_type_none_when_unspecified():
    """A declared column without a 'data_type' produces Column(data_type=None)."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "columns": [{"name": "email"}],
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    orders = next(
        s for s in result if isinstance(s, Table) and s.full_name == "cat.sales.orders"
    )
    (email_col,) = orders.columns
    assert email_col.data_type is None


def test_securables_compiler_preserves_column_declaration_order():
    """The order of columns in the YAML list is preserved in Table.columns (tuple)."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "columns": [
                                        {"name": "c_zebra", "type": "STRING"},
                                        {"name": "a_apple", "type": "INT"},
                                        {"name": "m_mango", "type": "DATE"},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    orders = next(
        s for s in result if isinstance(s, Table) and s.full_name == "cat.sales.orders"
    )
    assert [c.full_name.rsplit(".", 1)[-1] for c in orders.columns] == [
        "c_zebra",
        "a_apple",
        "m_mango",
    ]


def test_securables_compiler_emits_securable_for_each_declared_volume():
    """Every declared volume appears in the desired-securables set as a base Securable."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat": {
                    "schemas": [
                        {
                            "name": "raw",
                            "volumes": [
                                {"name": "events"},
                                {"name": "files"},
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    assert (
        Securable(securable_type=SecurableType.VOLUME, full_name="cat.raw.events")
        in result
    )
    assert (
        Securable(securable_type=SecurableType.VOLUME, full_name="cat.raw.files")
        in result
    )


def test_securables_compiler_emits_function_subclass_for_each_declared_function():
    """Functions continue to be emitted as Function instances, not base Securables."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "cat": {
                    "schemas": [
                        {
                            "name": "shared",
                            "functions": [
                                {"name": "greet", "return": "'hi'"},
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    func = next(s for s in result if s.full_name == "cat.shared.greet")
    assert isinstance(func, Function)


def test_securables_compiler_emits_nothing_for_empty_config():
    """A config with no catalogs produces an empty desired-securables set."""
    config = ResourcesConfig.model_validate({"catalogs": {}})

    assert compile_desired_securables(config) == set()


# ---------------------------------------------------------------------------
# compile_desired_securables — CREATE-time comment + location plumbing
# ---------------------------------------------------------------------------


def test_securables_compiler_plumbs_comment_and_location_onto_catalog_securable():
    """Catalog Securable carries comment and managed location for CREATE-time SQL embedding."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "comment": "Prod",
                    "location": "s3://managed/my_cat",
                },
            },
        }
    )

    result = compile_desired_securables(config)

    catalog = next(
        s
        for s in result
        if s.full_name == "my_cat" and s.securable_type == SecurableType.CATALOG
    )
    assert catalog.comment == "Prod"
    assert catalog.location == "s3://managed/my_cat"


def test_securables_compiler_plumbs_comment_and_location_onto_schema_securable():
    """Schema Securable carries comment and managed location for CREATE-time SQL embedding."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "comment": "Sales",
                            "location": "s3://managed/sales",
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_securables(config)

    schema = next(s for s in result if s.full_name == "my_cat.sales")
    assert schema.comment == "Sales"
    assert schema.location == "s3://managed/sales"


def test_securables_compiler_plumbs_comment_and_location_onto_table_securable():
    """Table securable carries comment and external location for CREATE-time SQL embedding."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "comment": "Orders",
                                    "location": "s3://ext/orders",
                                    "columns": [{"name": "id", "type": "LONG"}],
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_securables(config)

    table = next(s for s in result if s.full_name == "my_cat.sales.orders")
    assert isinstance(table, Table)
    assert table.comment == "Orders"
    assert table.location == "s3://ext/orders"


def test_securables_compiler_plumbs_comment_and_location_onto_volume_securable():
    """Volume Securable carries comment and external location for CREATE-time SQL embedding."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "landing",
                            "volumes": [
                                {
                                    "name": "raw",
                                    "comment": "Raw",
                                    "location": "s3://ext/raw",
                                },
                            ],
                        },
                    ],
                },
            },
        }
    )

    result = compile_desired_securables(config)

    volume = next(s for s in result if s.full_name == "my_cat.landing.raw")
    assert volume.comment == "Raw"
    assert volume.location == "s3://ext/raw"


def test_securable_compiler_populates_column_comment_on_table_columns():
    """Column comment declared in config is propagated onto the Column inside the Table."""
    config = ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_cat": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "columns": [
                                        {
                                            "name": "order_id",
                                            "data_type": "LONG",
                                            "comment": "Unique order identifier",
                                        },
                                        {
                                            "name": "email",
                                            "data_type": "STRING",
                                            "comment": "Customer email address",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        }
    )

    result = compile_desired_securables(config)

    table = next(s for s in result if s.full_name == "my_cat.sales.orders")
    assert isinstance(table, Table)
    order_id_col = next(
        c for c in table.columns if c.full_name == "my_cat.sales.orders.order_id"
    )
    assert order_id_col.comment == "Unique order identifier"
    email_col = next(
        c for c in table.columns if c.full_name == "my_cat.sales.orders.email"
    )
    assert email_col.comment == "Customer email address"


# ---------------------------------------------------------------------------
# compile_desired_securables — filter-rule functions
# ---------------------------------------------------------------------------


def _filter_rule_function_config(function: dict) -> ResourcesConfig:
    """Wrap a single function config dict in a catalog/schema ResourcesConfig."""
    return ResourcesConfig.model_validate(
        {
            "catalogs": {
                "my_catalog": {
                    "schemas": [{"name": "shared", "functions": [function]}],
                }
            }
        }
    )


def _compiled_function(config: ResourcesConfig) -> Function:
    """Return the single Function compiled from ``config``."""
    return next(
        s for s in compile_desired_securables(config) if isinstance(s, Function)
    )


def _single_rls_rule(parameters: list[dict], rule: dict) -> RlsMappingRule:
    """Compile a function with one ``match_rules`` rls rule and return that rule."""
    config = _filter_rule_function_config(
        {
            "name": "row_filter",
            "parameters": parameters,
            "match_rules": [{"name": "rule", **rule}],
        }
    )
    filter_rules = _compiled_function(config).filter_rules
    assert filter_rules is not None
    (compiled_rule,) = filter_rules.all_of
    assert isinstance(compiled_rule, RlsMappingRule)
    return compiled_rule


def test_securable_compiler_emits_filter_rules_with_unresolved_principals():
    """A function defined by match_rules / match_any_of_rules compiles to a Function
    with an empty definition and a FilterRules spec: match_rules become all_of and
    match_any_of_rules become any_of (in list order), condition rules keep their
    condition, and rls_mapping principals stay unresolved (list values keep order).
    A single-parameter function's rls rule defaults its parameter to that one."""
    config = _filter_rule_function_config(
        {
            "name": "region_filter",
            "parameters": [{"name": "region", "type": "STRING"}],
            "match_rules": [
                {
                    "name": "region_access",
                    "rls_mapping": {
                        "AMER": "amer_readers",
                        "EMEA": ["emea_b", "emea_a"],
                    },
                },
                {"name": "not_deleted", "condition": "region IS NOT NULL"},
            ],
            "match_any_of_rules": [
                {"name": "admins", "condition": "is_account_group_member('admins')"},
                {
                    "name": "owners",
                    "identity": "current_user",
                    "rls_mapping": {"EMEA": "jdoe@example.com"},
                },
            ],
        }
    )

    func = _compiled_function(config)

    assert func.full_name == "my_catalog.shared.region_filter"
    assert func.parameters == (("region", "STRING"),)
    assert func.definition == ""
    assert func.filter_rules == FilterRules(
        all_of=(
            RlsMappingRule(
                name="region_access",
                parameter="region",
                operator="=",
                identity="is_account_group_member",
                entries=(
                    ("'AMER'", (_unknown_owner("amer_readers"),)),
                    ("'EMEA'", (_unknown_owner("emea_b"), _unknown_owner("emea_a"))),
                ),
            ),
            ConditionRule(name="not_deleted", condition="region IS NOT NULL"),
        ),
        any_of=(
            ConditionRule(name="admins", condition="is_account_group_member('admins')"),
            RlsMappingRule(
                name="owners",
                parameter="region",
                operator="=",
                identity="current_user",
                entries=(("'EMEA'", (_unknown_owner("jdoe@example.com"),)),),
            ),
        ),
    )


def test_securable_compiler_renders_rls_mapping_keys_as_typed_literals():
    """rls_mapping keys are rendered as canonical SQL literals of the rule's
    comparison type: an int key on an INT parameter, a date key on a DATE
    parameter, and an array_contains key on an ARRAY<STRING> parameter."""
    int_rule = _single_rls_rule(
        [{"name": "store_id", "type": "INT"}],
        {"rls_mapping": {42: "store_42_readers"}},
    )
    date_rule = _single_rls_rule(
        [{"name": "event_date", "type": "DATE"}],
        {"rls_mapping": {date(2026, 5, 2): "may_readers"}},
    )
    array_rule = _single_rls_rule(
        [{"name": "cities", "type": "ARRAY<STRING>"}],
        {"operator": "array_contains", "rls_mapping": {"Sydney": "sydney_readers"}},
    )

    assert [literal for literal, _ in int_rule.entries] == ["42"]
    assert [literal for literal, _ in date_rule.entries] == ["DATE'2026-05-02'"]
    assert [literal for literal, _ in array_rule.entries] == ["'Sydney'"]
    assert array_rule.operator == "array_contains"
    assert array_rule.parameter == "cities"


def test_securable_compiler_uses_explicit_rls_parameter_on_multi_parameter_function():
    """An rls rule's explicit parameter is kept, and its keys are typed against
    that parameter."""
    rule = _single_rls_rule(
        [{"name": "region", "type": "STRING"}, {"name": "store_id", "type": "INT"}],
        {"parameter": "store_id", "rls_mapping": {7: "store_7_readers"}},
    )

    assert rule.parameter == "store_id"
    assert rule.entries == (("7", (_unknown_owner("store_7_readers"),)),)


def test_securable_compiler_maps_wildcard_key_to_none():
    """The '*' wildcard key compiles to a None literal, alongside typed entries in
    mapping order."""
    rule = _single_rls_rule(
        [{"name": "region", "type": "STRING"}],
        {"rls_mapping": {"AMER": "amer_readers", "*": ["global_a", "global_b"]}},
    )

    assert rule.entries == (
        ("'AMER'", (_unknown_owner("amer_readers"),)),
        (None, (_unknown_owner("global_a"), _unknown_owner("global_b"))),
    )


def test_securable_compiler_keeps_filter_rules_none_for_return_function():
    """A function defined by ``return`` compiles with its definition and no
    filter_rules."""
    config = _filter_rule_function_config(
        {
            "name": "greet",
            "parameters": [{"name": "x", "type": "STRING"}],
            "return": "x = 'hi'",
        }
    )

    func = _compiled_function(config)

    assert func.definition == "x = 'hi'"
    assert func.filter_rules is None
