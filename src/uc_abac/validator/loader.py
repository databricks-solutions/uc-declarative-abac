from __future__ import annotations

from pathlib import Path
from typing import Literal

from uc_abac.configs import (
    ResourcesConfig,
    consolidate_resources,
    discover_yaml_files,
    load_raw_configs,
    resolve_refs,
)


def load_config(
    config_dir: Path,
    ref_override_strategy: Literal["merge", "replace"] = "merge",
) -> ResourcesConfig:
    """Discover, resolve, and validate YAML configs without contacting Databricks."""
    paths = discover_yaml_files(config_dir)
    raw_defs, raw_resources = load_raw_configs(paths)
    resolved = resolve_refs(
        raw_defs, raw_resources, override_strategy=ref_override_strategy
    )
    consolidated = consolidate_resources(resolved)
    return ResourcesConfig.model_validate(consolidated)
