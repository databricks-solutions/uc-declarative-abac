"""HTTP contract tests for ABAC Policy Explorer query and explanation endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI

from abac_viewer.backend.engine.runtime import (
    BuildInfo,
    get_build_info,
    get_model,
)
from abac_viewer.backend.router import access_graph, router
from tests.unit.abac_viewer.dump_fixtures import load_dump_model

FIXTURE = Path(__file__).parent / "fixtures" / "nested"
# Dump rows carry config paths relative to the directory uc-abac dump ran in.
NESTED_CONFIG = "tests/unit/abac_viewer/fixtures/nested/configs.yaml"
GITHUB_BLOB = "https://github.com/example/abac/blob/abc123"
TABLE = "acme.sales.orders"
COLUMN = f"{TABLE}.customer_email"
SERVICE_PRINCIPALS = (
    "sp_alice",
    "sp_bob",
    "sp_carol",
    "sp_dave",
    "sp_erin",
    "sp_frank",
)


@pytest.fixture(scope="module")
def model():
    return load_dump_model(FIXTURE, service_principals=SERVICE_PRINCIPALS)


@pytest.fixture(scope="module")
def api_app(model):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_model] = lambda: model
    app.dependency_overrides[get_build_info] = lambda: BuildInfo(
        sha="abc123",
        repo_slug="example/abac",
        config_path_prefix="",
    )
    return app


@pytest.fixture(scope="module")
def client(api_app):
    return AsgiClient(api_app)


class AsgiResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.body = body

    def json(self):
        return json.loads(self.body)


class AsgiClient:
    def __init__(self, app: FastAPI):
        self.app = app

    def get(self, path: str, params: dict[str, str] | None = None) -> AsgiResponse:
        return asyncio.run(self._get(path, params or {}))

    async def _get(self, path: str, params: dict[str, str]) -> AsgiResponse:
        messages = []
        request_sent = False

        async def receive():
            nonlocal request_sent
            if request_sent:
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": urlencode(params).encode(),
            "headers": [],
            "client": ("test-client", 50000),
            "server": ("test-server", 80),
            "root_path": "",
        }
        with contextlib.suppress(Exception):
            await self.app(scope, receive, send)

        start = next(
            (
                message
                for message in messages
                if message["type"] == "http.response.start"
            ),
            None,
        )
        if start is None:
            return AsgiResponse(500, b"")
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return AsgiResponse(start["status"], body)


def test_openapi_exposes_column_contracts(api_app):
    paths = api_app.openapi()["paths"]

    assert paths["/api/columns"]["get"]["operationId"] == "columnsForPrincipal"
    assert paths["/api/column-policies"]["get"]["operationId"] == "listColumnPolicies"
    assert paths["/api/explain-column"]["get"]["operationId"] == "explainColumn"
    assert (
        paths["/api/explain-column-graph"]["get"]["operationId"] == "explainColumnGraph"
    )


def test_columns_endpoint_returns_masked_column_rows(client):
    response = client.get(
        "/api/columns",
        params={"principal": "sp_alice", "filter": "masked"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert all(row["masked"] for row in rows)
    assert all(row["mask_targeted"] for row in rows)
    assert {row["table"]: row["row_filtered"] for row in rows} == {
        "acme.hr.employees": False,
        TABLE: False,
    }
    assert not any(row["row_filter_targeted"] for row in rows)
    assert {row["column_full_name"] for row in rows} == {
        "acme.hr.employees.full_name",
        COLUMN,
    }
    assert set(rows[0]) == {
        "table",
        "column",
        "column_full_name",
        "data_type",
        "can_read_table",
        "mask_targeted",
        "masked",
        "row_filtered",
        "row_filter_targeted",
        "principal",
        "policy_name",
        "tags",
    }


def test_columns_endpoint_can_scope_results_to_one_table(client):
    response = client.get(
        "/api/columns",
        params={"principal": "sp_alice", "filter": "all", "table": TABLE},
    )

    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert {row["table"] for row in rows} == {TABLE}


def test_columns_endpoint_can_include_inaccessible_columns(client):
    response = client.get(
        "/api/columns",
        params={
            "principal": "sp_frank",
            "filter": "all",
            "include_inaccessible": "true",
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert not any(row["can_read_table"] for row in rows)
    exempt = next(row for row in rows if row["column_full_name"] == COLUMN)
    assert exempt["mask_targeted"] is True
    assert exempt["masked"] is False
    assert exempt["policy_name"] == "mask_pii"


def test_column_policy_endpoint_returns_targeted_effects(client):
    response = client.get("/api/column-policies")

    assert response.status_code == 200
    policies = {row["column_full_name"]: row for row in response.json()}
    assert policies[COLUMN]["mask_policy_count"] == 1
    assert policies[COLUMN]["row_filter_policy_count"] == 0


def test_principals_distinguish_users_service_principals_and_groups(client):
    response = client.get("/api/principals")

    assert response.status_code == 200
    kinds = {principal["name"]: principal["kind"] for principal in response.json()}
    assert kinds["sp_alice"] == "service_principal"
    assert kinds["analysts"] == "group"
    assert "anonymous" not in kinds


def test_tree_endpoint_includes_table_effect_rollups(client):
    response = client.get("/api/tree", params={"principal": "sp_alice"})

    assert response.status_code == 200
    catalog = next(node for node in response.json() if node["full_name"] == "acme")
    sales = next(
        node for node in catalog["children"] if node["full_name"] == "acme.sales"
    )
    orders = next(node for node in sales["children"] if node["full_name"] == TABLE)
    assert orders["readable"] is True
    assert orders["row_filtered"] is True
    assert orders["row_filter_targeted"] is True
    assert orders["masked_column_count"] == 1
    assert orders["mask_policy_column_count"] == 1
    assert orders["column_count"] == 3


def test_inventory_tree_rolls_row_filter_policies_up_to_tables(client):
    response = client.get("/api/tree")

    assert response.status_code == 200
    catalog = next(node for node in response.json() if node["full_name"] == "acme")
    sales = next(
        node for node in catalog["children"] if node["full_name"] == "acme.sales"
    )
    orders = next(node for node in sales["children"] if node["full_name"] == TABLE)
    assert orders["row_filter_targeted"] is True
    assert orders["row_filtered"] is None


def test_access_graph_exposes_progressive_grant_hops(client):
    response = client.get("/api/graph", params={"principal": "sp_alice"})

    assert response.status_code == 200
    body = response.json()
    nodes = {node["id"]: node["kind"] for node in body["nodes"]}
    edges = {
        (edge["source"], edge["target"], edge["kind"], edge["label"])
        for edge in body["edges"]
    }
    assert nodes["sp_alice"] == "user"
    assert nodes["analysts_emea"] == "group"
    assert nodes["analysts"] == "group"
    assert nodes["acme#grant_gold_read"] == "policy"
    tag_id = "tag:acme#grant_gold_read:zone=gold"
    assert nodes[tag_id] == "tag"
    assert nodes[TABLE] == "table"
    table_node = next(node for node in body["nodes"] if node["id"] == TABLE)
    assert table_node["row_filter_targeted"] is True
    assert table_node["row_filtered"] is True
    assert "acme" not in nodes
    assert "acme.sales" not in nodes
    assert ("sp_alice", "analysts_emea", "membership", "member") in edges
    assert ("analysts_emea", "analysts", "membership", "member") in edges
    assert (
        "analysts",
        "acme#grant_gold_read",
        "to",
        "in 'to'",
    ) in edges
    assert (
        "acme#grant_gold_read",
        tag_id,
        "matches",
        "matches",
    ) in edges
    assert (
        tag_id,
        TABLE,
        "tagged",
        "SELECT",
    ) in edges


def test_access_graph_nodes_link_to_exact_config_lines(client):
    response = client.get("/api/graph", params={"principal": "sp_alice"})

    assert response.status_code == 200
    body = response.json()
    nodes = {node["id"]: node for node in body["nodes"]}
    for node_id in [
        "analysts",
        "acme#grant_gold_read",
        TABLE,
    ]:
        assert nodes[node_id]["source"] == NESTED_CONFIG
        assert nodes[node_id]["github_url"] == f"{GITHUB_BLOB}/{NESTED_CONFIG}"
    assert nodes["sp_alice"]["github_url"] is None
    assert nodes["tag:acme#grant_gold_read:zone=gold"]["github_url"] is None
    tagged_edge = next(
        edge
        for edge in body["edges"]
        if edge["target"] == TABLE and edge["kind"] == "tagged"
    )
    assert tagged_edge["code_sources"] == [
        {
            "securable": TABLE,
            "securable_type": "table",
            "source": NESTED_CONFIG,
            "github_url": f"{GITHUB_BLOB}/{NESTED_CONFIG}",
            "inherited": False,
        }
    ]


def test_access_graph_tables_link_to_the_tagged_parent():
    fixture = Path(__file__).parent / "fixtures" / "parallel_grants"
    model = load_dump_model(fixture)
    build = BuildInfo(
        sha="abc123",
        repo_slug="example/abac",
        config_path_prefix="",
    )

    graph = access_graph("sp_engineer", model, build)
    nodes = {node.id: node for node in graph.nodes}
    tagged_edges = [
        edge
        for edge in graph.edges
        if edge.target == "acme.finance.budgets" and edge.kind == "tagged"
    ]
    assert len(tagged_edges) == 2
    assert all(
        [source.securable for source in edge.code_sources] == ["acme.finance"]
        for edge in tagged_edges
    )
    assert all(
        edge.code_sources[0].source.endswith("parallel_grants/configs.yaml")
        for edge in tagged_edges
    )
    assert all(edge.code_sources[0].inherited for edge in tagged_edges)
    assert nodes["sp_engineer"].github_url is None
    assert all(node.github_url is None for node in graph.nodes if node.kind == "tag")


def test_access_graph_tables_keep_table_and_parent_tag_sources():
    fixture = Path(__file__).parent / "fixtures" / "table_and_parent_tags"
    model = load_dump_model(fixture)
    build = BuildInfo(
        sha="abc123",
        repo_slug="example/abac",
        config_path_prefix="",
    )

    graph = access_graph("sp_reader", model, build)
    tagged_edge = next(
        edge
        for edge in graph.edges
        if edge.target == "acme.finance.budgets" and edge.kind == "tagged"
    )

    assert [source.securable for source in tagged_edge.code_sources] == [
        "acme.finance.budgets",
        "acme.finance",
    ]
    assert all(
        source.source.endswith("table_and_parent_tags/configs.yaml")
        for source in tagged_edge.code_sources
    )
    assert [source.inherited for source in tagged_edge.code_sources] == [False, True]
    assert all(source.github_url for source in tagged_edge.code_sources)


def test_access_graph_projects_inherited_grants_to_tables(client):
    response = client.get("/api/graph", params={"principal": "data_platform"})

    assert response.status_code == 200
    body = response.json()
    nodes = {node["id"]: node["kind"] for node in body["nodes"]}
    edges = {
        (edge["source"], edge["target"], edge["kind"], edge["label"])
        for edge in body["edges"]
    }
    assert nodes["acme#grant_platform_traverse"] == "policy"
    assert nodes["acme.sales#grant_platform_schema"] == "policy"
    assert nodes["acme.sales.orders"] == "table"
    assert nodes["acme.sales.leads"] == "table"
    assert (
        "data_platform",
        "acme#grant_platform_traverse",
        "to",
        "in 'to'",
    ) in edges
    assert (
        "acme.sales#grant_platform_schema",
        "acme.sales.orders",
        "grant",
        "SELECT",
    ) in edges


def test_inverse_graph_returns_only_paths_to_selected_table(client):
    response = client.get("/api/inverse-graph", params={"securable": TABLE})

    assert response.status_code == 200
    body = response.json()
    assert body["target"] == TABLE
    assert body["target_type"] == "table"
    table_nodes = {node["id"] for node in body["nodes"] if node["kind"] == "table"}
    assert table_nodes == {TABLE}
    alice = next(
        effect
        for effect in body["principal_effects"]
        if effect["principal"] == "sp_alice"
    )
    assert alice["masked"] is True
    assert alice["row_filtered"] is True
    assert alice["mask_policy_columns"] == [COLUMN]
    alice_node = next(node for node in body["nodes"] if node["id"] == "sp_alice")
    assert alice_node["effect_principal"] is True
    assert alice_node["mask_targeted"] is True
    assert alice_node["masked"] is True
    assert alice_node["row_filter_targeted"] is True
    assert alice_node["row_filtered"] is True
    analysts = next(
        effect
        for effect in body["principal_effects"]
        if effect["principal"] == "analysts"
    )
    assert analysts["masked"] is True
    analysts_node = next(node for node in body["nodes"] if node["id"] == "analysts")
    assert analysts_node["effect_principal"] is True
    assert analysts_node["mask_targeted"] is False
    assert analysts_node["masked"] is False
    assert analysts_node["row_filter_targeted"] is False
    assert analysts_node["row_filtered"] is False


def test_table_explanation_exposes_row_filter_targeting(client):
    response = client.get(
        "/api/explain",
        params={"principal": "sp_alice", "table": TABLE},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["row_filter_targeted"] is True
    assert body["row_filtered"] is True
    assert body["row_filter_excepted_by"] is None


def test_inverse_graph_scopes_mask_status_to_selected_column(client):
    response = client.get("/api/inverse-graph", params={"securable": COLUMN})

    assert response.status_code == 200
    body = response.json()
    assert body["target_type"] == "column"
    assert any(
        node["id"] == COLUMN and node["kind"] == "column" for node in body["nodes"]
    )
    assert any(
        edge["source"] == TABLE
        and edge["target"] == COLUMN
        and edge["kind"] == "contains"
        for edge in body["edges"]
    )
    alice = next(
        effect
        for effect in body["principal_effects"]
        if effect["principal"] == "sp_alice"
    )
    assert alice["masked_columns"] == [COLUMN]
    assert alice["row_filter_columns"] == []
    amount = client.get(
        "/api/inverse-graph",
        params={"securable": f"{TABLE}.amount"},
    ).json()
    amount_alice = next(
        effect
        for effect in amount["principal_effects"]
        if effect["principal"] == "sp_alice"
    )
    assert amount_alice["masked"] is False
    assert amount_alice["row_filtered"] is True


def test_inverse_graph_rejects_unknown_target(client):
    response = client.get(
        "/api/inverse-graph",
        params={"securable": "acme.sales.missing"},
    )

    assert response.status_code == 404


def test_explain_column_endpoint_serializes_deciding_policy(client):
    response = client.get(
        "/api/explain-column",
        params={"principal": "sp_alice", "column": COLUMN},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "sp_alice"
    assert body["column_full_name"] == COLUMN
    assert body["table_full_name"] == TABLE
    assert body["can_read_table"] is True
    assert body["masked"] is True
    assert body["row_filtered"] is False
    assert body["row_filter_targeted"] is False
    assert body["row_filter_excepted_by"] is None
    assert body["policy_name"] == "mask_pii"
    assert body["tag_atoms"] == {"pii": "email"}
    assert body["arguments"] == [
        {
            "position": 1,
            "kind": "alias",
            "alias": "pii_col",
            "constant": None,
            "constant_type": None,
            "target": True,
            "matched_columns": ["customer_email"],
        }
    ]


def test_column_graph_endpoint_adds_pinned_github_links(client):
    response = client.get(
        "/api/explain-column-graph",
        params={"principal": "sp_alice", "column": COLUMN},
    )

    assert response.status_code == 200
    body = response.json()
    nodes = body["nodes"]
    policy = next(node for node in nodes if node["id"] == "acme#mask_pii")
    user = next(node for node in nodes if node["kind"] == "user")
    tag = next(node for node in nodes if node["kind"] == "tag")
    tagged_edge = next(edge for edge in body["edges"] if edge["kind"] == "tagged")
    assert policy["github_url"] == f"{GITHUB_BLOB}/{NESTED_CONFIG}"
    assert user["sublabel"] == "user"
    assert tag["sublabel"] == "tag"
    assert tagged_edge["code_sources"][0]["securable"] == COLUMN
    assert (
        tagged_edge["code_sources"][0]["github_url"] == f"{GITHUB_BLOB}/{NESTED_CONFIG}"
    )


def test_table_graph_endpoint_hides_masks_but_keeps_filters(client):
    response = client.get(
        "/api/explain-graph",
        params={
            "principal": "sp_alice",
            "table": TABLE,
            "include_column_masks": "false",
        },
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {node["id"] for node in body["nodes"]}
    assert "acme#mask_pii" not in node_ids
    assert "acme.sales#filter_gold_rows" in node_ids
    assert not any(node["kind"] == "column" for node in body["nodes"])
    assert any(edge["label"] == "FILTERS ROWS" for edge in body["edges"])


def test_table_graph_endpoint_can_return_filter_only_flow(client):
    response = client.get(
        "/api/explain-graph",
        params={
            "principal": "sp_alice",
            "table": TABLE,
            "include_column_masks": "false",
            "include_grants": "false",
        },
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {node["id"] for node in body["nodes"]}
    assert "acme.sales#filter_gold_rows" in node_ids
    assert "acme#grant_gold_read" not in node_ids


def test_table_graph_endpoint_scopes_filters_to_focused_column(client):
    response = client.get(
        "/api/explain-graph",
        params={
            "principal": "sp_alice",
            "table": TABLE,
            "include_column_masks": "false",
            "include_grants": "false",
            "focus_column": "customer_email",
        },
    )

    assert response.status_code == 200
    node_ids = {node["id"] for node in response.json()["nodes"]}
    assert "acme.sales#filter_gold_rows" not in node_ids


def test_columns_endpoint_rejects_unknown_filter(client):
    response = client.get(
        "/api/columns",
        params={"principal": "sp_alice", "filter": "unexpected"},
    )

    assert response.status_code == 422


def test_explain_column_rejects_malformed_identifier(client):
    response = client.get(
        "/api/explain-column",
        params={"principal": "sp_alice", "column": "customer_email"},
    )

    assert response.status_code == 422


def test_explain_column_returns_not_found_for_unknown_column(client):
    response = client.get(
        "/api/explain-column",
        params={
            "principal": "sp_alice",
            "column": "acme.sales.orders.does_not_exist",
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/api/who-can-see", "/api/explain-column-graph"])
def test_other_column_endpoints_validate_identifiers(client, path):
    malformed = client.get(path, params={"principal": "sp_alice", "column": "email"})
    unknown = client.get(
        path,
        params={
            "principal": "sp_alice",
            "column": "acme.sales.orders.does_not_exist",
        },
    )

    assert malformed.status_code == 422
    assert unknown.status_code == 404
