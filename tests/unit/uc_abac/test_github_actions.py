"""Supply chain guardrails for the repo's CI: GitHub Actions and the Read the Docs build.

The CI workflow runs pull requests from public forks, and the composite actions run inside
consumers' deploy jobs alongside their Databricks credentials, so both must only execute
pinned, hash-verified third-party code:

- every external action is pinned to a full commit SHA (including in documented examples);
- every ``setup-uv`` step installs one exact, identical uv version;
- the workflow's token is read-only and never persisted into the checkout;
- fork pull requests run on GitHub-hosted runners rather than the protected runner group;
- the composite actions install only hash-verified packages and never build the project
  with an unpinned, isolated build backend;
- Dependabot watches every directory that holds actions;
- Read the Docs installs the same pinned uv as CI and only hash-verified packages.

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

_SHA_PINNED_REF = re.compile(r"@[0-9a-f]{40}$")
_PLACEHOLDER_REF = re.compile(r"@<[^>]+>$")
_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_DOCS_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
_ASDF_UV_INSTALL = re.compile(r"^asdf install uv (\S+)$")


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


def _composite_run_lines() -> list[str]:
    """Return every logical shell line of every composite action ``run`` block."""
    scripts = [step["run"] for step in _composite_steps() if "run" in step]
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


def test_ci_workflow_runs_fork_pull_requests_on_github_hosted_runners():
    jobs = _load_yaml(_CI_WORKFLOW)["jobs"]
    offenders = [
        name
        for name, job in jobs.items()
        if not (
            isinstance(job["runs-on"], str)
            and "head.repo.full_name" in job["runs-on"]
            and "ubuntu-latest" in job["runs-on"]
        )
    ]
    assert not offenders, (
        f"Jobs that do not route fork PRs to ubuntu-latest: {offenders}"
    )


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
        line for line in _composite_run_lines() if line.startswith("uv pip install")
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


def test_readthedocs_config_installs_only_hash_verified_packages():
    config = _load_yaml(_READTHEDOCS_CONFIG)
    installs = [
        command for command in _readthedocs_commands() if "pip install" in command
    ]
    assert "install" not in config.get("python", {})
    assert installs
    assert all("--require-hashes" in command for command in installs)
