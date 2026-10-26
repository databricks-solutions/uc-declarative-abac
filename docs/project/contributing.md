(contributing)=

# Contributing

Thank you for considering contributing to UC Declarative ABAC. Contributions are managed through GitHub, and we want the experience to be friendly and low-friction.

## How to contribute

- **Bugs and feature requests**: open a [GitHub Issue](https://github.com/databricks-solutions/uc-declarative-abac/issues) with what you expected, what happened, and a minimal repro where relevant
- **Questions, ideas, and design discussion**: start a [GitHub Discussion](https://github.com/databricks-solutions/uc-declarative-abac/discussions)
- **Code changes**: fork the repo, create a branch, and open a Pull Request against `main`. Keep PRs focused and smaller PRs get reviewed faster. All PRs are reviewed by code owners listed in [`.github/CODEOWNERS`](https://github.com/databricks-solutions/uc-declarative-abac/blob/main/.github/CODEOWNERS)

## Getting started with development

Set up your environment using `uv`:

```bash
uv venv
uv sync --extra dev
```

Run the test suite:

```bash
.venv/bin/pytest tests/unit -q
```

## Building the documentation locally

The docs are written in MyST Markdown and built with Sphinx. To build them locally:

```bash
uv sync --extra docs
.venv/bin/sphinx-build -W --keep-going -n -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` in your browser to preview.

## Documentation rules

- **Customer-facing only.** Document observable behaviour and configuration, not engine
  internals such as query shapes, SDK calls, or internal class names.
- **No en dashes (U+2013) or em dashes (U+2014).** Rewrite each one by meaning: commas or a new
  sentence for asides, a colon for "term: explanation", a semicolon for joined clauses, and
  `None` in tables for "no default". A unit test enforces this.
- **No warnings.** The build runs with `-W`, so any warning fails CI and Read the Docs.
- **MyST conventions.** Link pages with `{ref}` roles to `(label)=` targets, and use directive
  fences for admonitions and captioned code blocks.

## Full contributor guide

See the full [CONTRIBUTING.md](https://github.com/databricks-solutions/uc-declarative-abac/blob/main/CONTRIBUTING.md) for coding conventions, the development workflow, and our code of conduct.

See [AGENTS.md](https://github.com/databricks-solutions/uc-declarative-abac/blob/main/AGENTS.md) for the test and design practices used in this repository.
