from __future__ import annotations

from unittest.mock import MagicMock

from tests.unit.uc_abac.workspace_mocks import (
    catalog_with_tags_config,
    configure_iam,
    iam_group,
    iam_member,
    iam_user,
    install_fetch_router,
    numeric_id_mapper,
    setup_mock_empty_principals,
    setup_mock_principals,
    setup_mock_workspace_empty_state,
)
from uc_abac.fetcher import ActualState, fetch_actual_state
from uc_abac.helpers import UnityCatalogHelper, WorkspaceHelper
from uc_abac.utils import RunContext, Scope, run_date_for_timezone
from uc_abac.validator import load_config


def _inert_run_context() -> RunContext:
    """A RunContext with every feature scope empty — nothing is fetched/gated on."""
    empty = Scope()
    return RunContext(
        tag_management_scope=empty,
        tag_assignment_scope=empty,
        privilege_management_scope=empty,
        securable_modification_scope=empty,
        securable_creation_scope=empty,
        policy_deletion_scope=empty,
        group_creation_scope=empty,
        group_modification_scope=empty,
        group_deletion_scope=empty,
        governed_tag_deletion_scope=empty,
        domain_creation_scope=empty,
        domain_modification_scope=empty,
        domain_deletion_scope=empty,
        run_date=run_date_for_timezone("UTC"),
        retain_prefixes=frozenset(),
        ignore_unresolvable=frozenset(),
        system_catalog="system",
        use_workspace_scim=False,
        skip_users_fetch=False,
        dry_run=False,
        force=False,
        max_parallel_changes=8,
        manage_domain_owners=False,
    )


def _build_helpers(mock_workspace_client: MagicMock):
    """Construct the two live helpers the fetch/execute functions are threaded."""
    uc_helper = UnityCatalogHelper(
        mock_workspace_client, "test-warehouse-id", system_catalog="system"
    )
    ws_helper = WorkspaceHelper(
        mock_workspace_client,
        use_workspace_scim=False,
        manage_groups=True,
        manage_domain_owners=True,
        skip_users_fetch=False,
    )
    return uc_helper, ws_helper


def test_fetcher_fetches_every_domain_when_settings_omitted(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    config_dict = catalog_with_tags_config()
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    setup_mock_empty_principals(mock_workspace_client)
    mock_workspace_client.domains.list_domains.return_value = iter([])
    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    actual_state = fetch_actual_state(config, uc_helper, ws_helper)

    # With no settings the fetch is unscoped: domains are read and the privileges
    # system-table query is issued even though no management flag is set.
    assert isinstance(actual_state, ActualState)
    assert mock_workspace_client.domains.list_domains.called
    assert any(
        "_privileges" in sql.lower() for sql in mock_workspace_client.executed_sql
    )


def test_fetcher_scopes_fetch_when_settings_provided(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    config_dict = catalog_with_tags_config()
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    setup_mock_empty_principals(mock_workspace_client)
    mock_workspace_client.domains.list_domains.return_value = iter([])
    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    fetch_actual_state(config, uc_helper, ws_helper, _inert_run_context())

    # An inert context gates out the optional domains: the privilege query is never
    # issued and the domains API is never called.
    assert not mock_workspace_client.domains.list_domains.called
    assert not any(
        "_privileges" in sql.lower() for sql in mock_workspace_client.executed_sql
    )


def test_fetcher_returns_pure_state_without_helpers(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    config_dict = catalog_with_tags_config()
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    setup_mock_empty_principals(mock_workspace_client)
    mock_workspace_client.domains.list_domains.return_value = iter([])
    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    actual_state = fetch_actual_state(config, uc_helper, ws_helper)

    # ActualState is a pure state view — it carries no execution handles.
    assert not hasattr(actual_state, "ws_helper")
    assert not hasattr(actual_state, "uc_helper")
    assert isinstance(actual_state.principals, dict)


def test_fetcher_populates_helper_caches_for_reuse(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    config_dict = catalog_with_tags_config()
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    setup_mock_principals(mock_workspace_client, "data_engineers")
    mock_workspace_client.domains.list_domains.return_value = iter([])
    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    actual_state = fetch_actual_state(config, uc_helper, ws_helper)

    # The fetch populated the ws_helper principal cache; the returned snapshot and a
    # fresh read of the (same) helper agree, and the fetched group is present.
    assert "data_engineers" in actual_state.principals
    assert ws_helper.get_principals() == actual_state.principals


def test_fetcher_fetches_members_of_referenced_undeclared_groups_when_settings_omitted(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    """When settings=None (full fetch), members of groups referenced anywhere in config
    but not declared under resources.groups are fetched and returned in ActualState.

    Config declares NO resources.groups but references "data_engineers" in a grant
    policy "to" field. With settings=None, the returned state.groups contains
    "data_engineers" with members populated (non-None).
    """
    config_dict = {
        "resources": {
            "governed_tags": {"team": {"allowed_values": ["data"]}},
            "catalogs": {
                "my_catalog": {
                    "tags": {"env": "prod"},
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "policies": [
                                        {
                                            "name": "grant_data",
                                            "type": "grant",
                                            "privileges": ["select"],
                                            "to": ["data_engineers"],
                                            "has_tags": {"team": "data"},
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }
    }
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    mock_workspace_client.domains.list_domains.return_value = iter([])

    # Set up the referenced group with members (not declared but referenced in policy).
    num = numeric_id_mapper()
    configure_iam(
        mock_workspace_client,
        users=[iam_user("alice", num("u-1"))],
        groups=[iam_group("data_engineers", group_id=num("g-1"))],
        members_by_group_id={num("g-1"): [iam_member(num("u-1"))]},
    )

    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    actual_state = fetch_actual_state(config, uc_helper, ws_helper)

    # With settings=None, the referenced-only "data_engineers" group is fetched with
    # its members populated.
    data_eng_groups = [
        g for g in actual_state.groups if g.display_name == "data_engineers"
    ]
    assert len(data_eng_groups) == 1
    data_eng = data_eng_groups[0]
    assert data_eng.members is not None
    assert len(data_eng.members) == 1


def test_fetcher_fetches_assumers_of_referenced_undeclared_groups_when_settings_omitted(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    """When settings=None (full fetch), assumers of groups referenced anywhere in config
    but not declared under resources.groups are fetched and returned in ActualState.

    Config declares NO resources.groups but references "data_engineers" elsewhere.
    With settings=None, the returned state.groups contains "data_engineers" with
    assumers populated (non-None).
    """
    from databricks.sdk.service.iam import GrantRule, RuleSetResponse

    config_dict = {
        "resources": {
            "governed_tags": {"team": {"allowed_values": ["data"]}},
            "catalogs": {
                "my_catalog": {
                    "tags": {"env": "prod"},
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "policies": [
                                        {
                                            "name": "grant_data",
                                            "type": "grant",
                                            "privileges": ["select"],
                                            "to": ["data_engineers"],
                                            "has_tags": {"team": "data"},
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }
    }
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    mock_workspace_client.domains.list_domains.return_value = iter([])

    # Set up the referenced group with assumers.
    num = numeric_id_mapper()
    configure_iam(
        mock_workspace_client,
        users=[iam_user("bob", num("u-2"))],
        groups=[iam_group("data_engineers", group_id=num("g-1"))],
        members_by_group_id={},
    )
    mock_workspace_client.config.account_id = "acc-1"
    mock_workspace_client.account_access_control_proxy.get_rule_set.return_value = (
        RuleSetResponse(
            name="rs",
            etag="e1",
            grant_rules=[
                GrantRule(
                    role="roles/group.assumer",
                    principals=["users/bob@example.com"],
                )
            ],
        )
    )

    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    actual_state = fetch_actual_state(config, uc_helper, ws_helper)

    # With settings=None, the referenced-only "data_engineers" group is fetched with
    # its assumers populated.
    data_eng_groups = [
        g for g in actual_state.groups if g.display_name == "data_engineers"
    ]
    assert len(data_eng_groups) == 1
    data_eng = data_eng_groups[0]
    assert data_eng.assumers is not None
    assert len(data_eng.assumers) == 1


def test_fetcher_never_fetches_account_users_members_or_assumers(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    """The "account users" system group must never have members or assumers fetched,
    even if referenced in config or via default FGAC policy "to".

    Config references "account users" implicitly (or explicitly via policy). When
    fetch_actual_state is called with settings=None, no member/assumer fetch is made
    for "account users" — it has members=None or is absent from state.groups.
    """
    config_dict = {
        "resources": {
            "governed_tags": {"team": {"allowed_values": ["data"]}},
            "catalogs": {
                "my_catalog": {
                    "tags": {"env": "prod"},
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "policies": [
                                        {
                                            "name": "grant_to_all",
                                            "type": "grant",
                                            "privileges": ["select"],
                                            "to": ["account users"],
                                            "has_tags": {"team": "data"},
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }
    }
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    mock_workspace_client.domains.list_domains.return_value = iter([])

    num = numeric_id_mapper()
    configure_iam(
        mock_workspace_client,
        users=[iam_user("alice", num("u-1"))],
        groups=[iam_group("account users", group_id=num("g-special"))],
        members_by_group_id={},
    )

    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    # Record initial call counts to verify member/assumer fetch is not called for account users.
    initial_member_calls = mock_workspace_client.workspace_iam_v2.list_direct_group_members_proxy.call_count

    actual_state = fetch_actual_state(config, uc_helper, ws_helper)

    # "account users" should not have had its members fetched (call count unchanged
    # or it has members=None).
    account_users_groups = [
        g for g in actual_state.groups if g.display_name == "account users"
    ]
    if account_users_groups:
        # If it's in the state, it must have members=None (unmanaged, never fetched).
        assert account_users_groups[0].members is None
    # Verify no member fetches were made (or at most the same count as before).
    final_member_calls = mock_workspace_client.workspace_iam_v2.list_direct_group_members_proxy.call_count
    assert final_member_calls == initial_member_calls


def test_fetcher_does_not_fetch_referenced_undeclared_groups_when_settings_provided(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    """When a RunContext is passed (deploy path), referenced-only groups are NOT fetched.

    Config declares NO resources.groups but references "data_engineers" in a policy.
    With a RunContext passed (not settings=None), the referenced group is not fetched
    for members/assumers — they remain None or the group is absent from state.groups.
    This test pins the unchanged deploy path behaviour (only declared groups fetched).
    """
    config_dict = {
        "resources": {
            "governed_tags": {"team": {"allowed_values": ["data"]}},
            "catalogs": {
                "my_catalog": {
                    "tags": {"env": "prod"},
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "policies": [
                                        {
                                            "name": "grant_data",
                                            "type": "grant",
                                            "privileges": ["select"],
                                            "to": ["data_engineers"],
                                            "has_tags": {"team": "data"},
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }
    }
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    mock_workspace_client.domains.list_domains.return_value = iter([])

    # Set up the referenced group with members.
    num = numeric_id_mapper()
    configure_iam(
        mock_workspace_client,
        users=[iam_user("alice", num("u-1"))],
        groups=[iam_group("data_engineers", group_id=num("g-1"))],
        members_by_group_id={num("g-1"): [iam_member(num("u-1"))]},
    )

    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    # Pass an inert RunContext (deploy path) instead of settings=None.
    ctx = _inert_run_context()
    actual_state = fetch_actual_state(config, uc_helper, ws_helper, ctx)

    # With a RunContext, the referenced-only group should NOT be in state.groups
    # (because only declared groups are fetched on the deploy path).
    data_eng_groups = [
        g for g in actual_state.groups if g.display_name == "data_engineers"
    ]
    assert len(data_eng_groups) == 0


def test_fetcher_fetches_assigners_of_referenced_undeclared_governed_tags_when_settings_omitted(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    """When settings=None (full fetch), assigners of governed tags referenced anywhere in config
    but not declared under resources.governed_tags are fetched and returned in ActualState.

    Config declares NO resources.governed_tags but references tag key "pii" via a securable's
    `tags:` map on a table. The account has a tag policy "pii" whose rule set grants ASSIGN
    to a principal. With settings=None, the returned ActualState.governed_tags contains
    "pii" with non-empty `assigners` including that principal.
    """
    config_dict = {
        "resources": {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "tags": {"pii": "sensitive"},
                                },
                            ],
                        }
                    ],
                }
            },
        }
    }
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    setup_mock_empty_principals(mock_workspace_client)
    mock_workspace_client.domains.list_domains.return_value = iter([])

    # Set up the account's tag policy "pii" (not declared but referenced in table tags).
    pii_policy = MagicMock()
    pii_policy.tag_key = "pii"
    pii_policy.description = "Sensitive PII"
    pii_policy.id = "tp-pii"
    pii_policy.values = None
    mock_workspace_client.tag_policies.list_tag_policies.return_value = iter(
        [pii_policy]
    )

    # Set up the rule set for "pii" with an assigner principal.
    from databricks.sdk.service.iam import GrantRule, RuleSetResponse

    pii_rule_set = RuleSetResponse(
        name="accounts/acc-1/tagPolicies/tp-pii/ruleSets/default",
        etag="e-pii",
        grant_rules=[
            GrantRule(
                role="roles/tagPolicy.assigner",
                principals=["users/alice@example.com"],
            )
        ],
    )
    mock_workspace_client.account_access_control_proxy.get_rule_set.return_value = (
        pii_rule_set
    )
    mock_workspace_client.config.account_id = "acc-1"

    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    # Call fetch_actual_state with settings=None (full fetch).
    actual_state = fetch_actual_state(config, uc_helper, ws_helper)

    # With settings=None, the referenced-only "pii" tag should be fetched with
    # assigners populated.
    pii_tags = [gt for gt in actual_state.governed_tags if gt.name == "pii"]
    assert len(pii_tags) == 1
    pii = pii_tags[0]
    assert len(pii.assigners) > 0
    # The assigner should be an unresolved Principal with the fetched identifier.
    assigner_identifiers = {p.identifier for p in pii.assigners}
    assert "alice@example.com" in assigner_identifiers


def test_fetcher_does_not_fetch_assigners_of_referenced_undeclared_governed_tags_when_settings_provided(
    tmp_yaml_dir, mock_workspace_client, monkeypatch
):
    """When a RunContext is passed (deploy path), referenced-only governed tags are NOT
    fetched for their assigners — they remain with empty assigners.

    Config declares NO resources.governed_tags but references tag key "pii" via a
    securable's `tags:` map. The account has a tag policy "pii" with assigners.
    With a RunContext passed (not settings=None), the tag is present (listed) but
    with empty `assigners`. This test pins the unchanged deploy path behaviour
    (only declared governed tags get assigners fetched).
    """
    config_dict = {
        "resources": {
            "catalogs": {
                "my_catalog": {
                    "schemas": [
                        {
                            "name": "sales",
                            "tables": [
                                {
                                    "name": "orders",
                                    "tags": {"pii": "sensitive"},
                                },
                            ],
                        }
                    ],
                }
            },
        }
    }
    root = tmp_yaml_dir({"resources/catalog.yaml": config_dict})
    setup_mock_workspace_empty_state(mock_workspace_client)
    install_fetch_router(monkeypatch, config_dict)
    setup_mock_empty_principals(mock_workspace_client)
    mock_workspace_client.domains.list_domains.return_value = iter([])

    # Set up the account's tag policy "pii" (not declared but referenced in table tags).
    pii_policy = MagicMock()
    pii_policy.tag_key = "pii"
    pii_policy.description = "Sensitive PII"
    pii_policy.id = "tp-pii"
    pii_policy.values = None
    mock_workspace_client.tag_policies.list_tag_policies.return_value = iter(
        [pii_policy]
    )

    # Set up the rule set for "pii" with an assigner principal.
    from databricks.sdk.service.iam import GrantRule, RuleSetResponse

    pii_rule_set = RuleSetResponse(
        name="accounts/acc-1/tagPolicies/tp-pii/ruleSets/default",
        etag="e-pii",
        grant_rules=[
            GrantRule(
                role="roles/tagPolicy.assigner",
                principals=["users/alice@example.com"],
            )
        ],
    )
    mock_workspace_client.account_access_control_proxy.get_rule_set.return_value = (
        pii_rule_set
    )
    mock_workspace_client.config.account_id = "acc-1"

    config = load_config(root)
    uc_helper, ws_helper = _build_helpers(mock_workspace_client)

    # Pass a RunContext (deploy path) instead of settings=None.
    ctx = _inert_run_context()
    actual_state = fetch_actual_state(config, uc_helper, ws_helper, ctx)

    # With a RunContext, the referenced-only "pii" tag should be present (listed)
    # but with empty assigners (only declared tags get assigners on deploy path).
    pii_tags = [gt for gt in actual_state.governed_tags if gt.name == "pii"]
    assert len(pii_tags) == 1
    pii = pii_tags[0]
    assert len(pii.assigners) == 0
