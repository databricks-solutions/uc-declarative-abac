"""Tests for the project's documentation.

The documentation (README, CONTRIBUTING, the Sphinx site under ``docs/``, and the example
READMEs) must not contain en dashes (U+2013) or em dashes (U+2014); each one is rewritten with a
semicolon, comma, colon, or period instead. The dash characters are written as escapes so this
file itself stays clean.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHES = ("–", "—")


def _documentation_files() -> list[Path]:
    """Return every documentation file to scan, excluding Sphinx build output."""
    docs = _REPO_ROOT / "docs"
    candidates = [
        _REPO_ROOT / "README.md",
        _REPO_ROOT / "CONTRIBUTING.md",
        *docs.glob("**/*.md"),
        *docs.glob("_templates/*.html"),
        *(_REPO_ROOT / "examples").glob("**/README.md"),
    ]
    return sorted(
        path
        for path in candidates
        if "_build" not in path.relative_to(_REPO_ROOT).parts
    )


def _dash_offenders(path: Path) -> list[str]:
    """Return ``<path>:<line>: <text>`` for every line of ``path`` containing a dash."""
    relative = path.relative_to(_REPO_ROOT)
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        f"{relative}:{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if any(dash in line for dash in _DASHES)
    ]


def test_docs_contain_no_en_or_em_dashes():
    offenders = [
        offender
        for path in _documentation_files()
        for offender in _dash_offenders(path)
    ]

    assert not offenders, (
        "En dashes and em dashes are not allowed in documentation. Rewrite each one with a "
        "semicolon, comma, colon, or period:\n" + "\n".join(offenders)
    )
