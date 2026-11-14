"""Shared workspace-client mock helpers for the orchestrator and fetcher tests.

The account identity path runs on Workspace Identity V2 (workspace_iam_v2), not the
raw account SCIM proxy. List proxies return typed objects; ids are numeric strings
(DirectGroupMember.principal_id is an int), and the helper casts to int at the
membership-call boundary, so all ids here are numeric strings.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def iam_user(user_name: str, user_id: str = "1") -> SimpleNamespace:
    """Stand-in for a databricks.sdk.service.iamv2.User."""
    return SimpleNamespace(username=user_name, user_id=user_id)


def iam_group(
    display_name: str, group_id: str = "10", external_id: str = ""
) -> SimpleNamespace:
    """Stand-in for a databricks.sdk.service.iamv2.Group (never carries members)."""
    return SimpleNamespace(
        group_name=display_name, group_id=group_id, external_id=external_id
    )


def iam_sp(
    display_name: str, application_id: str, sp_id: str = "100"
) -> SimpleNamespace:
    """Stand-in for a databricks.sdk.service.iamv2.ServicePrincipal."""
    return SimpleNamespace(
        display_name=display_name,
        application_id=application_id,
        service_principal_id=sp_id,
    )


def iam_member(principal_id: str | int) -> SimpleNamespace:
    """Stand-in for a databricks.sdk.service.iamv2.DirectGroupMember."""
    return SimpleNamespace(principal_id=int(principal_id))


def configure_iam(
    mock_workspace_client: MagicMock,
    *,
    users: list[SimpleNamespace] | None = None,
    groups: list[SimpleNamespace] | None = None,
    service_principals: list[SimpleNamespace] | None = None,
    members_by_group_id: dict[str, list[SimpleNamespace]] | None = None,
) -> MagicMock:
    """Configure the ``workspace_iam_v2`` list/member proxies on a mock client.

    Returns the ``workspace_iam_v2`` mock so tests can set create/update/delete
    behaviours or inspect mutation calls. Each list proxy returns a fresh iterator per
    call; ``list_direct_group_members_proxy`` serves members keyed by group id.
    """
    iam = mock_workspace_client.workspace_iam_v2
    iam.list_users_proxy.side_effect = lambda **kwargs: iter(list(users or []))
    iam.list_groups_proxy.side_effect = lambda **kwargs: iter(list(groups or []))
    iam.list_service_principals_proxy.side_effect = lambda **kwargs: iter(
        list(service_principals or [])
    )
    members = {str(k): v for k, v in (members_by_group_id or {}).items()}
    iam.list_direct_group_members_proxy.side_effect = lambda group_id, **kwargs: iter(
        members.get(str(group_id), [])
    )
    return iam


def catalog_with_tags_config() -> dict:
    """A minimal YAML dict: one catalog with tags on catalog and a schema."""
    return {
        "resources": {
            "catalogs": {
                "my_catalog": {
                    "tags": {"env": "prod"},
                    "schemas": [
                        {"name": "sales", "tags": {"team": "data"}},
                    ],
                }
            }
        }
    }


def setup_mock_workspace_empty_state(mock_workspace_client: MagicMock) -> None:
    """Configure the mock workspace client to return empty actual state.

    Each returned response carries ``._sql`` (the executed statement) so that a
    monkeypatched ``_fetch_external_links_rows`` can route by SQL content.
    """
    from databricks.sdk.service.sql import StatementState

    def _capture_and_return(*args, **kwargs):
        statement = kwargs.get("statement", args[0] if args else None)
        if statement:
            mock_workspace_client.executed_sql.append(statement)
        response = MagicMock()
        response.status.state = StatementState.SUCCEEDED
        response.result.data_array = []
        response.result.external_links = []
        response._sql = statement
        return response

    mock_workspace_client.statement_execution.execute_statement.side_effect = (
        _capture_and_return
    )


def securable_existence_rows(config_dict: dict) -> list[list]:
    """Build securables-fetch rows matching every catalog/schema/table/volume declared
    in a resources-config dict, *after consolidation* (so consolidator-auto-created
    schemas like ``default`` are included). Row format matches fetch_actual_securables:
    ``[securable_type, full_name, owner, parameters_json, routine_definition, routine_comment]``.
    """
    import copy

    from uc_abac.configs import consolidate_resources

    resources = copy.deepcopy(config_dict.get("resources") or {})
    consolidated = consolidate_resources(resources)
    catalogs = consolidated.get("catalogs") or {}

    rows: list[list] = []
    for cat_key, cat in catalogs.items():
        cat_data = cat if isinstance(cat, dict) else {}
        cat_name = cat_data.get("name", cat_key)
        rows.append(["CATALOG", cat_name, None, None, None, None])
        for schema in cat_data.get("schemas") or []:
            if not isinstance(schema, dict):
                continue
            schema_name = schema.get("name")
            if not schema_name:
                continue
            schema_full = f"{cat_name}.{schema_name}"
            rows.append(["SCHEMA", schema_full, None, None, None, None])
            for table in schema.get("tables") or []:
                if isinstance(table, dict) and table.get("name"):
                    rows.append(
                        [
                            "TABLE",
                            f"{schema_full}.{table['name']}",
                            None,
                            None,
                            None,
                            None,
                        ]
                    )
            for vol in schema.get("volumes") or []:
                if isinstance(vol, dict) and vol.get("name"):
                    rows.append(
                        [
                            "VOLUME",
                            f"{schema_full}.{vol['name']}",
                            None,
                            None,
                            None,
                            None,
                        ]
                    )
    return rows


def install_fetch_router(
    monkeypatch,
    config_dict: dict,
    tag_rows: list[list] | None = None,
    privilege_rows: list[list] | None = None,
    policy_securable_rows: list[list] | None = None,
) -> None:
    """Monkeypatch ``_fetch_external_links_rows`` so it routes by the executed SQL:

    - securables query -> existence rows for every declared catalog/schema/table/volume
      in ``config_dict`` (so the differ's nonexistent-securable check passes),
    - tags query -> ``tag_rows`` or ``[]``,
    - privileges query -> ``privilege_rows`` or ``[]``,
    - policy-discovery query (``abac_policy_definitions``) -> ``policy_securable_rows``
      or ``[]``. Each row is ``[on_securable_type, full_name]`` and represents a
      securable that carries a mask/filter policy in UC — the helper then fans out
      ``list_policies`` per discovered securable to get full detail. An empty list
      means "no actual policies exist", so the fan-out is skipped entirely.
    - anything else -> ``[]``.

    Assumes each response returned by execute_statement carries ``._sql`` — set by
    ``setup_mock_workspace_empty_state`` and its cousins.
    """
    sec_rows = securable_existence_rows(config_dict)

    def _route(response):
        sql = (getattr(response, "_sql", "") or "").lower()
        if "abac_policy_definitions" in sql:
            return policy_securable_rows or []
        if "catalog_owner" in sql or "schema_owner" in sql or "routine_owner" in sql:
            return sec_rows
        if any(
            t in sql
            for t in (
                "catalog_tags",
                "schema_tags",
                "table_tags",
                "volume_tags",
                "column_tags",
            )
        ):
            return tag_rows or []
        if "_privileges" in sql:
            return privilege_rows or []
        return []

    monkeypatch.setattr(
        "uc_abac.helpers.unity_catalog._fetch_external_links_rows",
        _route,
    )


def setup_mock_principals(mock_workspace_client: MagicMock, group_name: str) -> None:
    """Configure the account identity proxy to return a single group."""
    configure_iam(mock_workspace_client, groups=[iam_group(group_name)])


def setup_mock_empty_principals(mock_workspace_client: MagicMock) -> None:
    """Configure the account identity proxy to return no principals."""
    configure_iam(mock_workspace_client)


def setup_mock_principals_with_groups(
    mock_workspace_client: MagicMock, group_names: list[str]
) -> None:
    """Configure the account identity proxy to return specific groups and no users/SPs."""
    configure_iam(
        mock_workspace_client,
        groups=[
            iam_group(name, group_id=str(10 + i)) for i, name in enumerate(group_names)
        ],
    )


def numeric_id_mapper():
    """Return a function that maps arbitrary string ids (``"g-1"``, ``"u-1"``) to stable
    numeric-string ids. V2 principal ids are numeric and the helper ``int()``-casts them
    at the membership-call boundary, so mocks must return numeric ids; callers keep their
    readable labels and this translates them consistently across users/groups/members."""
    numeric: dict[str, str] = {}

    def _num(raw: str) -> str:
        if raw not in numeric:
            numeric[raw] = str(1000 + len(numeric))
        return numeric[raw]

    return _num
