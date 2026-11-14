from __future__ import annotations

import pytest

from uc_abac.validator import load_config


def test_loader_sets_file_path_on_every_config_model(tmp_yaml_dir):
    """Every config model in the loaded tree (bar the root, which aggregates every file)
    records the file its content was written in — across $refs, overrides, standalone
    resources, auto-created parents, inline policy functions and account-level resources."""
    from pydantic import BaseModel

    root = tmp_yaml_dir(
        {
            "definitions/catalogs.yaml": {
                "definitions": {
                    "catalogs": {
                        "sales": {
                            "schemas": [
                                {
                                    "name": "orders",
                                    "tables": [
                                        {
                                            "name": "orders",
                                            "columns": [
                                                {"name": "id", "data_type": "INT"}
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            },
            "resources/prod.yaml": {
                "resources": {
                    "catalogs": {
                        "sales_prod": {
                            "$ref": "$defs/catalogs/sales",
                            "schemas": [{"name": "returns"}],
                        }
                    }
                }
            },
            "resources/standalone.yaml": {
                "resources": {
                    "tables": {
                        "other|s|events": {
                            "name": "events",
                            "catalog_name": "other",
                            "schema_name": "s",
                        }
                    },
                    "policies": {
                        "sales_prod|mask_pii": {
                            "name": "mask_pii",
                            "type": "mask",
                            "catalog_name": "sales_prod",
                            "schema_name": "orders",
                            "function": {
                                "name": "mask_email",
                                "parameters": [{"name": "col", "type": "STRING"}],
                                "return": "col",
                            },
                            "columns": [
                                {"alias": "email", "has_tags": {"pii": "email"}}
                            ],
                        }
                    },
                    "governed_tags": {"pii": {"allowed_values": ["email"]}},
                    "groups": {"analysts": {}},
                }
            },
        }
    )
    definitions_file = root / "definitions/catalogs.yaml"
    prod_file = root / "resources/prod.yaml"
    standalone_file = root / "resources/standalone.yaml"

    config = load_config(root)

    def walk(node, trail):
        if isinstance(node, BaseModel):
            yield trail, node
            for name in type(node).model_fields:
                yield from walk(getattr(node, name), f"{trail}.{name}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                yield from walk(item, f"{trail}[{i}]")
        elif isinstance(node, dict):
            for key, item in node.items():
                yield from walk(item, f"{trail}[{key!r}]")

    unattributed = [
        trail
        for trail, m in walk(config, "config")
        if trail != "config" and m.file_path is None
    ]
    assert unattributed == []

    schemas = {s.name: s for s in config.catalogs["sales_prod"].schemas}
    orders_table = schemas["orders"].tables[0]
    assert config.catalogs["sales_prod"].file_path == definitions_file
    assert schemas["orders"].file_path == definitions_file
    assert orders_table.file_path == definitions_file
    assert orders_table.columns[0].file_path == definitions_file
    assert schemas["returns"].file_path == prod_file

    other = config.catalogs["other"]
    assert other.file_path == standalone_file
    assert other.schemas[0].file_path == standalone_file
    assert other.schemas[0].tables[0].file_path == standalone_file

    policy = schemas["orders"].policies[0]
    function = next(f for f in schemas["orders"].functions if f.name == "mask_email")
    assert policy.file_path == standalone_file
    assert function.file_path == standalone_file
    assert function.parameters[0].file_path == standalone_file

    assert config.governed_tags["pii"].file_path == standalone_file
    assert config.groups["analysts"].file_path == standalone_file


def test_loader_loads_tag_maps_shared_via_definitions(tmp_yaml_dir):
    """Tag maps shared under ``definitions.tags`` load cleanly, whether referenced via a
    ``$ref`` with overrides or an inline ``$defs/...`` string: the engine's source-file stamp
    on the tag-map definition never leaks into the resulting tags as a ``file_path`` tag."""
    root = tmp_yaml_dir(
        {
            "definitions/tags.yaml": {
                "definitions": {
                    "tags": {
                        "base_tags": {"owner": "platform"},
                        "pii_email": {"pii": "email"},
                    }
                }
            },
            "resources/c.yaml": {
                "resources": {
                    "catalogs": {
                        "cat1": {
                            "tags": {"$ref": "$defs/tags/base_tags", "env": "prod"},
                            "schemas": [
                                {
                                    "name": "s",
                                    "policies": [
                                        {
                                            "name": "mask_pii",
                                            "type": "mask",
                                            "function": "cat1.s.mask_fn",
                                            "columns": [
                                                {
                                                    "alias": "email_col",
                                                    "has_tags": "$defs/tags/pii_email",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                }
            },
        }
    )
    resources_file = root / "resources/c.yaml"

    config = load_config(root)

    assert config.catalogs["cat1"].tags == {"owner": "platform", "env": "prod"}
    assert config.catalogs["cat1"].file_path == resources_file

    schema = config.catalogs["cat1"].schemas[0]
    assert schema.name == "s"
    assert schema.file_path == resources_file

    policy = schema.policies[0]
    column = policy.columns[0]
    assert column.alias == "email_col"
    assert column.has_tags == {"pii": "email"}


@pytest.mark.parametrize(
    "case_id,yaml_files",
    [
        (
            "catalog_with_file_path_string",
            {
                "resources/c.yaml": {
                    "resources": {
                        "catalogs": {
                            "cat1": {
                                "file_path": "x.yaml",
                            }
                        }
                    }
                }
            },
        ),
        (
            "catalog_with_file_path_null",
            {
                "resources/c.yaml": {
                    "resources": {
                        "catalogs": {
                            "cat1": {
                                "file_path": None,
                            }
                        }
                    }
                }
            },
        ),
        (
            "schema_with_file_path_string",
            {
                "resources/c.yaml": {
                    "resources": {
                        "catalogs": {
                            "cat1": {
                                "schemas": [
                                    {
                                        "name": "s",
                                        "file_path": "x.yaml",
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        ),
        (
            "schema_with_file_path_null",
            {
                "resources/c.yaml": {
                    "resources": {
                        "catalogs": {
                            "cat1": {
                                "schemas": [
                                    {
                                        "name": "s",
                                        "file_path": None,
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        ),
        (
            "definition_catalog_with_file_path_string_and_ref",
            {
                "definitions/catalogs.yaml": {
                    "definitions": {
                        "catalogs": {
                            "base": {
                                "file_path": "user/written.yml",
                                "comment": "hi",
                            }
                        }
                    }
                },
                "resources/c.yaml": {
                    "resources": {
                        "catalogs": {
                            "c": {
                                "$ref": "$defs/catalogs/base",
                            }
                        }
                    }
                },
            },
        ),
        (
            "definition_catalog_with_file_path_null_and_ref",
            {
                "definitions/catalogs.yaml": {
                    "definitions": {
                        "catalogs": {
                            "base": {
                                "file_path": None,
                                "comment": "hi",
                            }
                        }
                    }
                },
                "resources/c.yaml": {
                    "resources": {
                        "catalogs": {
                            "c": {
                                "$ref": "$defs/catalogs/base",
                            }
                        }
                    }
                },
            },
        ),
    ],
)
def test_loader_rejects_user_written_file_path(tmp_yaml_dir, case_id, yaml_files):
    """User-written file_path in YAML (whether a string or null) must raise ValidationError.
    The file_path attribute is engine-owned and cannot be set by users. This applies to
    definitions and resources, inline or via $ref."""
    root = tmp_yaml_dir(yaml_files)

    with pytest.raises(Exception) as exc_info:
        load_config(root)

    # Should raise a validation error (pydantic.ValidationError) with "engine-owned" in message
    assert "ValidationError" in type(exc_info.value).__name__
    assert "engine-owned" in str(exc_info.value)


def test_loader_attributes_override_children_of_a_nested_ref(
    tmp_yaml_dir,
):
    """Children added as overrides on a $ref nested below the top level of an entry are
    attributed to the file the $ref was written in; the definition's own inline children,
    and the $ref'd schema itself, keep the definition's file."""
    root = tmp_yaml_dir(
        {
            "definitions/schemas.yaml": {
                "definitions": {
                    "schemas": {"s": {"name": "s", "tables": [{"name": "t1"}]}}
                }
            },
            "resources/prod.yaml": {
                "resources": {
                    "catalogs": {
                        "cat1": {
                            "schemas": [
                                {
                                    "$ref": "$defs/schemas/s",
                                    "tables": [{"name": "extra"}],
                                }
                            ]
                        }
                    }
                }
            },
        }
    )
    definitions_file = root / "definitions/schemas.yaml"

    config = load_config(root)

    schema = config.catalogs["cat1"].schemas[0]
    tables = {t.name: t for t in schema.tables}
    assert schema.file_path == definitions_file
    assert tables["t1"].file_path == definitions_file
    assert tables["extra"].file_path == root / "resources/prod.yaml"


def test_loader_attributes_a_referenced_policy_function_to_its_definition_file(
    tmp_yaml_dir,
):
    """A function referenced via $defs/$ref keeps its definition's file; inline functions
    take the policy's file.

    When a mask policy references a function defined in a separate definitions file via
    $defs/function_name, the extracted function retains its definition file. In contrast,
    a function written inline in a policy would inherit the policy's file.
    """
    root = tmp_yaml_dir(
        {
            "definitions/functions.yaml": {
                "definitions": {
                    "functions": {
                        "mask_pii": {
                            "name": "mask_pii",
                            "parameters": [{"name": "c", "type": "STRING"}],
                            "return": "c",
                        }
                    }
                }
            },
            "resources/r.yaml": {
                "resources": {
                    "catalogs": {
                        "cat1": {
                            "schemas": [
                                {
                                    "name": "s",
                                    "tables": [
                                        {
                                            "name": "t",
                                            "policies": [
                                                {
                                                    "name": "mask_policy",
                                                    "type": "mask",
                                                    "function": "$defs/functions/mask_pii",
                                                    "columns": [
                                                        {
                                                            "alias": "x",
                                                            "has_tags": {
                                                                "pii": "email"
                                                            },
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            },
        }
    )

    definitions_file = root / "definitions/functions.yaml"
    resources_file = root / "resources/r.yaml"

    config = load_config(root)

    schema = config.catalogs["cat1"].schemas[0]
    table = schema.tables[0]
    policy = table.policies[0]

    # Verify the policy itself is from resources/r.yaml
    assert policy.file_path == resources_file

    # Verify the function referenced via $defs keeps its definition file
    functions = schema.functions or []
    mask_pii_fn = next((f for f in functions if f.name == "mask_pii"), None)
    assert mask_pii_fn is not None, "mask_pii function should be extracted to schema"
    assert mask_pii_fn.file_path == definitions_file
