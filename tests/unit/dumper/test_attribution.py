"""Tests for dumper.attribution: mapping state objects back to their config file."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from uc_abac import ActualState
from uc_abac.dumper import build_config_paths
from uc_abac.orchestrator import load_config
from uc_abac.principals import Principal
from uc_abac.privileges import SecurablePrivilege
from uc_abac.tags import SecurableTag
from uc_abac.types import PrincipalType, PrivilegeType, SecurableType

_RUN_DATE = date(2026, 6, 1)

# --- Helpers ---


def _write(directory: Path, name: str, content: str) -> str:
    """Write a YAML file and return the POSIX path the dumper should report."""
    path = directory / name
    path.write_text(content)
    return path.as_posix()


def _state(**overrides: object) -> ActualState:
    defaults = {
        "groups": frozenset(),
        "all_account_groups": frozenset(),
        "governed_tags": frozenset(),
        "domains": frozenset(),
        "securables": frozenset(),
        "attributes": frozenset(),
        "tags": frozenset(),
        "policies": frozenset(),
        "privileges": frozenset(),
        "principals": {},
    }
    defaults.update(overrides)
    return ActualState(**defaults)  # type: ignore


def _paths(config_dir: Path, state: ActualState | None = None):
    return build_config_paths(load_config(config_dir), state or _state(), _RUN_DATE)


def _user(name: str) -> Principal:
    return Principal(PrincipalType.USER, identifier=name, name=name)


def _select_on(full_name: str, identifier: str) -> SecurablePrivilege:
    return SecurablePrivilege(
        SecurableType.TABLE,
        full_name,
        Principal(PrincipalType.UNKNOWN, identifier=identifier),
        PrivilegeType.SELECT,
    )


_CATALOG_YAML = """
resources:
  catalogs:
    main: {}
"""

_TABLE_YAML = """
resources:
  tables:
    sales|orders:
      catalog_name: main
      schema_name: sales
      name: orders
      columns:
        - name: email
"""

# --- Securables ---


def test_dumper_attribution_securable_path_by_type_and_full_name(tmp_path: Path):
    catalog_file = _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    table_file = _write(tmp_path, "table.yaml", _TABLE_YAML)

    paths = _paths(tmp_path)

    assert paths.securable(SecurableType.CATALOG, "main") == catalog_file
    assert paths.securable(SecurableType.TABLE, "main.sales.orders") == table_file


def test_dumper_attribution_column_path_from_column_config(tmp_path: Path):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    table_file = _write(tmp_path, "table.yaml", _TABLE_YAML)

    paths = _paths(tmp_path)

    assert paths.securable(SecurableType.COLUMN, "main.sales.orders.email") == (
        table_file
    )


def test_dumper_attribution_securable_path_requires_matching_type(tmp_path: Path):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    _write(tmp_path, "table.yaml", _TABLE_YAML)

    paths = _paths(tmp_path)

    assert paths.securable(SecurableType.VOLUME, "main.sales.orders") is None


# --- Policies ---


def test_dumper_attribution_policy_path_by_attached_securable_and_name(
    tmp_path: Path,
):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    policy_file = _write(
        tmp_path,
        "table.yaml",
        """
resources:
  tables:
    sales|orders:
      catalog_name: main
      schema_name: sales
      name: orders
      policies:
        - name: mask_email
          type: mask
          function: main.sales.mask_fn
          columns:
            - alias: e
              has_tags: {pii: email}
          to: [analysts]
""",
    )

    paths = _paths(tmp_path)

    assert (
        paths.policy(SecurableType.TABLE, "main.sales.orders", "mask_email")
        == policy_file
    )
    assert paths.policy(SecurableType.SCHEMA, "main.sales", "mask_email") is None


def test_dumper_attribution_policy_path_for_catalog_and_schema_policies(
    tmp_path: Path,
):
    catalog_file = _write(
        tmp_path,
        "catalog.yaml",
        """
resources:
  catalogs:
    main:
      policies:
        - name: catalog_filter
          type: filter
          function: main.sales.filter_fn
          to: [analysts]
""",
    )
    schema_file = _write(
        tmp_path,
        "schema.yaml",
        """
resources:
  schemas:
    main|sales:
      catalog_name: main
      name: sales
      policies:
        - name: schema_mask
          type: mask
          function: main.sales.mask_fn
          columns:
            - alias: e
              has_tags: {pii: email}
          to: [analysts]
""",
    )

    paths = _paths(tmp_path)

    assert paths.policy(SecurableType.CATALOG, "main", "catalog_filter") == (
        catalog_file
    )
    assert paths.policy(SecurableType.SCHEMA, "main.sales", "schema_mask") == (
        schema_file
    )
    assert paths.policy(SecurableType.TABLE, "main", "catalog_filter") is None
    assert paths.policy(SecurableType.TABLE, "main.sales", "schema_mask") is None


# --- Governed tags, domains, groups ---


def test_dumper_attribution_governed_tag_and_domain_paths(tmp_path: Path):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    tag_file = _write(
        tmp_path,
        "tags.yaml",
        """
resources:
  governed_tags:
    pii:
      allowed_values: [email]
""",
    )
    domain_file = _write(
        tmp_path,
        "domains.yaml",
        """
resources:
  domains:
    finance:
      governed_tag: finance_domain
""",
    )

    paths = _paths(tmp_path)

    assert paths.governed_tag("pii") == tag_file
    assert paths.domain("finance_domain") == domain_file


def test_dumper_attribution_group_path_by_name(tmp_path: Path):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    group_file = _write(
        tmp_path,
        "groups.yaml",
        """
resources:
  groups:
    analysts: {}
""",
    )

    paths = _paths(tmp_path)

    assert paths.group("analysts") == group_file
    assert paths.group("analysts", "123") == group_file


def test_dumper_attribution_group_path_by_id_when_name_differs(tmp_path: Path):
    """A group declared with its id still matches after an account-side rename."""
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    group_file = _write(
        tmp_path,
        "groups.yaml",
        """
resources:
  groups:
    analysts:
      id: "123"
""",
    )

    paths = _paths(tmp_path)

    assert paths.group("old-analysts-name", "123") == group_file


# --- Privileges ---


def test_dumper_attribution_privilege_path_from_first_matching_grant_policy(
    tmp_path: Path,
):
    catalog_file = _write(
        tmp_path,
        "catalog.yaml",
        """
resources:
  catalogs:
    main:
      policies:
        - name: catalog_grant
          type: grant
          privileges: [select]
          to: [alice]
          has_tags: {pii: email}
""",
    )
    _write(
        tmp_path,
        "table.yaml",
        """
resources:
  tables:
    sales|orders:
      catalog_name: main
      schema_name: sales
      name: orders
      policies:
        - name: table_grant
          type: grant
          privileges: [select]
          to: [alice]
""",
    )
    state = _state(
        tags=frozenset(
            [SecurableTag(SecurableType.TABLE, "main.sales.orders", "pii", "email")]
        ),
        principals={"alice": _user("alice")},
    )

    paths = _paths(tmp_path, state)

    assert paths.privilege(_select_on("main.sales.orders", "alice")) == catalog_file


def test_dumper_attribution_privilege_path_matches_actual_tags(tmp_path: Path):
    """Tag-based grants match against the fetched (actual) tags."""
    catalog_file = _write(
        tmp_path,
        "catalog.yaml",
        """
resources:
  catalogs:
    main:
      policies:
        - name: catalog_grant
          type: grant
          privileges: [select]
          to: [alice]
          has_tags: {pii: email}
""",
    )
    _write(tmp_path, "table.yaml", _TABLE_YAML)
    principals = {"alice": _user("alice")}
    privilege = _select_on("main.sales.orders", "alice")

    untagged = _paths(tmp_path, _state(principals=principals))
    tagged = _paths(
        tmp_path,
        _state(
            principals=principals,
            tags=frozenset(
                [SecurableTag(SecurableType.TABLE, "main.sales.orders", "pii", "email")]
            ),
        ),
    )

    assert untagged.privilege(privilege) is None
    assert tagged.privilege(privilege) == catalog_file


def test_dumper_attribution_privilege_path_resolves_config_names_to_identifiers(
    tmp_path: Path,
):
    """A service principal is granted by display name in config but appears in the
    actual privilege by application id."""
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    table_file = _write(
        tmp_path,
        "table.yaml",
        """
resources:
  tables:
    sales|orders:
      catalog_name: main
      schema_name: sales
      name: orders
      policies:
        - name: sp_grant
          type: grant
          privileges: [select]
          to: [etl-sp]
""",
    )
    sp = Principal(
        PrincipalType.SERVICE_PRINCIPAL, identifier="app-uuid-1", name="etl-sp"
    )
    state = _state(principals={"etl-sp": sp})

    paths = _paths(tmp_path, state)

    assert paths.privilege(_select_on("main.sales.orders", "app-uuid-1")) == (
        table_file
    )
    assert paths.privilege(_select_on("main.sales.orders", "etl-sp")) is None


def test_dumper_attribution_privilege_path_none_when_only_expired_policy_matches(
    tmp_path: Path,
):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    _write(
        tmp_path,
        "table.yaml",
        """
resources:
  tables:
    sales|orders:
      catalog_name: main
      schema_name: sales
      name: orders
      policies:
        - name: expired_grant
          type: grant
          privileges: [select]
          to: [alice]
          expiry_date: 2026-01-01
""",
    )
    state = _state(principals={"alice": _user("alice")})

    paths = _paths(tmp_path, state)

    assert paths.privilege(_select_on("main.sales.orders", "alice")) is None


def test_dumper_attribution_privilege_path_none_when_no_policy_produces_it(
    tmp_path: Path,
):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)
    _write(
        tmp_path,
        "table.yaml",
        """
resources:
  tables:
    sales|orders:
      catalog_name: main
      schema_name: sales
      name: orders
      policies:
        - name: table_grant
          type: grant
          privileges: [select]
          to: [alice]
""",
    )
    state = _state(principals={"alice": _user("alice"), "bob": _user("bob")})

    paths = _paths(tmp_path, state)

    assert paths.privilege(_select_on("main.sales.orders", "bob")) is None


# --- Missing entries ---


def test_dumper_attribution_none_when_not_in_config(tmp_path: Path):
    _write(tmp_path, "catalog.yaml", _CATALOG_YAML)

    paths = _paths(tmp_path)

    assert paths.securable(SecurableType.CATALOG, "other") is None
    assert paths.policy(SecurableType.CATALOG, "main", "nope") is None
    assert paths.governed_tag("nope") is None
    assert paths.domain("nope") is None
    assert paths.group("nope", "999") is None
    assert paths.privilege(_select_on("main.sales.orders", "alice")) is None
