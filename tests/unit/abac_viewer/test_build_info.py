"""BuildInfo GitHub deep-link tests and the AppConfig-to-BuildInfo mapping."""

from __future__ import annotations

import pytest

from abac_viewer.backend.core._config import AppConfig
from abac_viewer.backend.engine.runtime import BuildInfo, build_info_from_config

# ---------------------------------------------------------------------------
# BuildInfo.github_url
# ---------------------------------------------------------------------------


def test_build_info_github_url_joins_prefix_and_path_pinned_to_sha():
    build = BuildInfo(
        sha="deadbeef",
        repo_slug="example-org/abac-configs",
        config_path_prefix="abac-demo-fixture/configs",
    )

    url = build.github_url("definitions/policies/mask.yaml")

    assert url is not None
    assert url.startswith("https://github.com/example-org/abac-configs/blob/deadbeef/")
    assert url.endswith("abac-demo-fixture/configs/definitions/policies/mask.yaml")


def test_build_info_github_url_appends_line_anchor_when_line_given():
    build = BuildInfo(
        sha="deadbeef",
        repo_slug="example-org/abac-configs",
        config_path_prefix="configs",
    )

    url = build.github_url("definitions/policies/mask.yaml", 17)

    assert url is not None
    assert url.endswith("#L17")
    assert "/configs/definitions/policies/mask.yaml" in url


def test_build_info_github_url_has_no_line_anchor_without_line():
    build = BuildInfo(
        sha="deadbeef",
        repo_slug="example-org/abac-configs",
        config_path_prefix="configs",
    )

    url = build.github_url("definitions/policies/mask.yaml")

    assert url is not None
    assert "#" not in url


def test_build_info_github_url_uses_path_as_is_when_prefix_empty():
    build = BuildInfo(
        sha="deadbeef",
        repo_slug="example-org/abac-configs",
        config_path_prefix="",
    )

    url = build.github_url("definitions/policies/mask.yaml")

    assert url is not None
    assert url.endswith("/blob/deadbeef/definitions/policies/mask.yaml")
    assert "//definitions" not in url
    assert "/blob/deadbeef//" not in url


def test_build_info_github_url_is_none_when_repo_slug_empty():
    build = BuildInfo(
        sha="deadbeef",
        repo_slug="",
        config_path_prefix="configs",
    )

    assert build.github_url("definitions/policies/mask.yaml", 17) is None


# ---------------------------------------------------------------------------
# build_info_from_config
# ---------------------------------------------------------------------------


def test_build_info_from_config_maps_settings_from_environment(monkeypatch):
    monkeypatch.setenv("ABAC_VIEWER_REPO_SLUG", "example-org/abac-configs")
    monkeypatch.setenv("ABAC_VIEWER_REPO_REF", "v1.2.3")
    monkeypatch.setenv("ABAC_VIEWER_CONFIG_PATH_PREFIX", "fixture/configs")

    build = build_info_from_config(AppConfig())

    assert build == BuildInfo(
        sha="v1.2.3",
        repo_slug="example-org/abac-configs",
        config_path_prefix="fixture/configs",
    )


def test_build_info_from_config_maps_settings_from_keyword_arguments():
    config = AppConfig(
        repo_slug="example-org/other-configs",
        repo_ref="0123456789abcdef",
        config_path_prefix="team/configs",
    )

    build = build_info_from_config(config)

    assert build.sha == "0123456789abcdef"
    assert build.repo_slug == "example-org/other-configs"
    assert build.config_path_prefix == "team/configs"


@pytest.mark.parametrize("slug", ["none", "NONE", "None"])
def test_build_info_from_config_disables_links_when_repo_slug_is_none(slug):
    build = build_info_from_config(AppConfig(repo_slug=slug))

    assert build.repo_slug == ""
    assert build.github_url("configs/x.yaml") is None


@pytest.mark.parametrize("prefix", [".", "./", ""])
def test_build_info_from_config_treats_dot_prefix_as_repository_root(prefix):
    config = AppConfig(repo_slug="example/abac", config_path_prefix=prefix)

    build = build_info_from_config(config)

    assert build.github_url("configs/x.yaml") == (
        "https://github.com/example/abac/blob/main/configs/x.yaml"
    )
