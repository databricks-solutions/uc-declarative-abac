"""Supply chain guardrails for the repo's CI: GitHub Actions and the Read the Docs build.

The CI workflow runs pull requests from public forks, and the composite actions run inside
consumers' deploy jobs alongside their Databricks credentials, so both must only execute
pinned, hash-verified third-party code:

- every external action is pinned to a full commit SHA (including in documented examples);
- every ``setup-uv`` step installs one exact, identical uv version;
- the workflow's token is read-only and never persisted into the checkout;
- every job runs on GitHub-hosted runners and installs from the default (public) index;
- CI installs only the locked packages, straight from uv.lock;
- only pushes to main save the uv cache;
- the composite actions install only hash-verified packages and never build the project
  with an unpinned, isolated build backend;
- Dependabot watches every directory that holds actions and the uv dependencies, checks
  monthly, and proposes only versions released at least a week ago;
- uv.lock resolves from no internal Databricks index, so it is installable from anywhere;
- bun.lock (the ABAC Policy Explorer UI) resolves from no internal Databricks registry;
- Read the Docs installs the same pinned uv as CI and only the locked packages.

The checks parse the YAML files directly; nothing is executed.
"""

import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_DEPENDABOT_CONFIG = _REPO_ROOT / ".github" / "dependabot.yml"
_COMPOSITE_ACTIONS = sorted(_REPO_ROOT.glob("*/action.yml"))
_ACTIONS_DOCS = _REPO_ROOT / "docs" / "deploying" / "github-actions.md"
_READTHEDOCS_CONFIG = _REPO_ROOT / ".readthedocs.yaml"
_UV_LOCK = _REPO_ROOT / "uv.lock"
_BUN_LOCK = _REPO_ROOT / "bun.lock"
_MIN_RELEASE_AGE_DAYS = 7

_SHA_PINNED_REF = re.compile(r"@[0-9a-f]{40}$")
_PLACEHOLDER_REF = re.compile(r"@<[^>]+>$")
_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_DOCS_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
_ASDF_UV_INSTALL = re.compile(r"^asdf install uv (\S+)$")
_DATABRICKS_URL = re.compile(r"https?://[^\s\"/]*databricks\.com\b")

_INDEX_OVERRIDES = {
    "UV_DEFAULT_INDEX",
    "UV_INDEX_URL",
    "UV_INDEX",
    "UV_EXTRA_INDEX_URL",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    """Parse ``path`` as YAML, keeping ``on`` as a string key rather than ``True``."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _workflow_steps() -> list[dict[str, Any]]:
    """Return every step of every job in the CI workflow."""
    jobs = _load_yaml(_CI_WORKFLOW)["jobs"]
    return [step for job in jobs.values() for step in job.get("steps", [])]


def _composite_steps() -> list[dict[str, Any]]:
    """Return every step of every composite action."""
    return [
        step
        for path in _COMPOSITE_ACTIONS
        for step in _load_yaml(path)["runs"]["steps"]
    ]


def _steps_using(steps: list[dict[str, Any]], action: str) -> list[dict[str, Any]]:
    """Return the steps whose ``uses`` references ``action`` (any ref)."""
    return [step for step in steps if step.get("uses", "").startswith(f"{action}@")]


def _run_lines(steps: list[dict[str, Any]]) -> list[str]:
    """Return every logical shell line of every ``run`` block in ``steps``."""
    scripts = [step["run"] for step in steps if "run" in step]
    return [
        line.strip()
        for script in scripts
        for line in script.replace("\\\n", " ").splitlines()
        if line.strip()
    ]


def _external_uses() -> list[str]:
    """Return every non-local ``uses`` reference across workflows, actions, and docs."""
    step_uses = [
        step["uses"]
        for step in _workflow_steps() + _composite_steps()
        if "uses" in step
    ]
    docs_uses = _DOCS_USES.findall(_ACTIONS_DOCS.read_text(encoding="utf-8"))
    return [uses for uses in step_uses + docs_uses if not uses.startswith("./")]


# ---
# ci workflow
# ---


def test_ci_workflow_grants_read_only_token_permissions():
    assert _load_yaml(_CI_WORKFLOW)["permissions"] == {"contents": "read"}


def test_ci_workflow_runs_every_job_on_github_hosted_runners():
    jobs = _load_yaml(_CI_WORKFLOW)["jobs"]
    offenders = [
        name for name, job in jobs.items() if job["runs-on"] != "ubuntu-latest"
    ]
    assert not offenders, f"Jobs that do not run on ubuntu-latest: {offenders}"


def test_ci_workflow_installs_from_the_default_index():
    jobs = _load_yaml(_CI_WORKFLOW)["jobs"]
    envs = [job.get("env", {}) for job in jobs.values()] + [
        step.get("env", {}) for step in _workflow_steps()
    ]
    overrides = {name for env in envs for name in env if name in _INDEX_OVERRIDES}
    assert not overrides, f"CI overrides the package index with: {overrides}"


def test_ci_workflow_installs_only_locked_packages():
    lines = _run_lines(_workflow_steps())
    syncs = [line for line in lines if line.startswith("uv sync")]
    assert syncs
    assert all("--frozen" in line for line in syncs)
    assert not [line for line in lines if "uv export" in line or "pip install" in line]


def test_ci_workflow_saves_the_uv_cache_only_on_push():
    offenders = [
        step["uses"]
        for step in _steps_using(_workflow_steps(), "astral-sh/setup-uv")
        if step.get("with", {}).get("save-cache")
        != "${{ github.event_name == 'push' }}"
    ]
    assert not offenders, f"setup-uv steps that save the cache from PRs: {offenders}"


def test_github_actions_checkout_steps_do_not_persist_credentials():
    offenders = [
        step["uses"]
        for step in _steps_using(_workflow_steps(), "actions/checkout")
        if step.get("with", {}).get("persist-credentials") != "false"
    ]
    assert not offenders, f"Checkout steps that persist credentials: {offenders}"


# ---
# composite actions
# ---


def test_github_actions_setup_uv_steps_pin_one_exact_uv_version():
    steps = _steps_using(_workflow_steps() + _composite_steps(), "astral-sh/setup-uv")
    versions = {step.get("with", {}).get("version", "") for step in steps}
    assert len(versions) == 1, f"setup-uv steps disagree on the uv version: {versions}"
    assert _EXACT_VERSION.match(versions.pop())


def test_github_actions_external_actions_are_sha_pinned():
    offenders = [
        uses
        for uses in _external_uses()
        if not (_SHA_PINNED_REF.search(uses) or _PLACEHOLDER_REF.search(uses))
    ]
    assert not offenders, f"Actions not pinned to a commit SHA: {offenders}"


def test_composite_actions_install_only_hash_verified_packages():
    installs = [
        line
        for line in _run_lines(_composite_steps())
        if line.startswith("uv pip install")
    ]
    requirement_installs = [line for line in installs if " -r " in line]
    project_installs = [line for line in installs if " -r " not in line]
    assert requirement_installs
    assert project_installs
    assert all("--require-hashes" in line for line in requirement_installs)
    assert all(
        "--no-deps" in line and "--no-build-isolation" in line
        for line in project_installs
    )


# ---
# dependabot config
# ---


def test_dependabot_config_covers_every_action_directory():
    updates = _load_yaml(_DEPENDABOT_CONFIG)["updates"]
    covered = {
        directory
        for update in updates
        if update["package-ecosystem"] == "github-actions"
        for directory in update.get("directories", [update.get("directory")])
    }
    expected = {"/"} | {f"/{path.parent.name}" for path in _COMPOSITE_ACTIONS}
    assert expected <= covered


def test_dependabot_config_checks_for_updates_monthly():
    updates = _load_yaml(_DEPENDABOT_CONFIG)["updates"]
    assert all(update["schedule"]["interval"] == "monthly" for update in updates)


def test_dependabot_config_proposes_only_versions_released_a_week_ago():
    updates = _load_yaml(_DEPENDABOT_CONFIG)["updates"]
    assert all(
        int(update["cooldown"]["default-days"]) >= _MIN_RELEASE_AGE_DAYS
        for update in updates
    )


def test_dependabot_config_covers_uv_dependencies():
    updates = _load_yaml(_DEPENDABOT_CONFIG)["updates"]
    assert any(
        update["package-ecosystem"] == "uv" and update.get("directory") == "/"
        for update in updates
    )


# ---
# uv lock
# ---


def test_uv_lock_resolves_from_no_internal_databricks_index():
    lines = _UV_LOCK.read_text(encoding="utf-8").splitlines()
    offenders = [n for n, line in enumerate(lines, 1) if _DATABRICKS_URL.search(line)]
    assert not offenders, (
        "uv.lock has internal Databricks index URLs; re-lock against public PyPI "
        f"(lines {offenders[:5]})"
    )


def test_bun_lock_resolves_from_no_internal_databricks_registry():
    lines = _BUN_LOCK.read_text(encoding="utf-8").splitlines()
    offenders = [n for n, line in enumerate(lines, 1) if _DATABRICKS_URL.search(line)]
    assert not offenders, (
        "bun.lock has internal Databricks registry URLs; re-lock against the public npm "
        f"registry (lines {offenders[:5]})"
    )


# ---
# read the docs config
# ---


def _readthedocs_commands() -> list[str]:
    """Return every command of every Read the Docs build job."""
    jobs = _load_yaml(_READTHEDOCS_CONFIG)["build"]["jobs"]
    return [command for commands in jobs.values() for command in commands]


def test_readthedocs_config_installs_the_same_uv_version_as_ci():
    setup_uv_steps = _steps_using(_workflow_steps(), "astral-sh/setup-uv")
    ci_versions = {step["with"]["version"] for step in setup_uv_steps}
    rtd_versions = {
        match.group(1)
        for command in _readthedocs_commands()
        if (match := _ASDF_UV_INSTALL.match(command))
    }
    assert rtd_versions == ci_versions


def test_readthedocs_config_installs_only_locked_packages():
    config = _load_yaml(_READTHEDOCS_CONFIG)
    commands = _readthedocs_commands()
    syncs = [command for command in commands if "uv sync" in command]
    assert "install" not in config.get("python", {})
    assert syncs
    assert all("--frozen" in command for command in syncs)
    assert not [
        command
        for command in commands
        if "uv export" in command or "pip install" in command
    ]
