(installation)=

# Installation

Clone the repository and install in editable mode using `uv`:

```bash
git clone https://github.com/liamperritt/uc-declarative-abac.git
cd uc-declarative-abac
uv venv
uv sync --extra dev
```

The package installs two console scripts:

| Command | Description |
|---------|-------------|
| `uc-abac` | Short alias (recommended) |
| `uc-declarative-abac` | Full package name |

Both point to the same entry point and are used the same way. The old `python -m uc_abac` invocation still works but is deprecated (see {ref}`deprecations`).

## Next steps

- {ref}`quickstart` to deploy your first config
- {ref}`cli` for the full command reference
- {ref}`feature-scopes` to understand scope flags
