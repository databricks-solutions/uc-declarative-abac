"""Map dumped state rows back to the config file that declares them.

``config_file_path`` on each dump row is the ``file_path`` (POSIX string) of the
config entry for the row's object, or NULL when the object isn't in the config.

Privileges have no config entry of their own: a privilege is attributed to the first
active grant policy (in config hierarchy order) whose matches against the *actual*
tags produce it. Grant policies name principals by display name while actual
privileges carry canonical identifiers (e.g. a service principal's application ID),
so each config name is mapped through ``ActualState.principals`` (keyed by display
name) before keying the lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from uc_declarative_abac.configs import (
    BasePolicyConfig,
    CatalogConfig,
    ColumnConfig,
    FunctionConfig,
    GrantPolicyConfig,
    ResourcesConfig,
    SchemaConfig,
    TableConfig,
    VolumeConfig,
    iter_policy_configs,
    iter_securable_configs,
)
from uc_declarative_abac.orchestrator import ActualState
from uc_declarative_abac.privileges import (
    SecurablePrivilege,
    match_grant_policy_privileges,
)
from uc_declarative_abac.types import PrivilegeType, SecurableType

_CONFIG_CLASS_TO_SECURABLE_TYPE = {
    CatalogConfig: SecurableType.CATALOG,
    SchemaConfig: SecurableType.SCHEMA,
    TableConfig: SecurableType.TABLE,
    ColumnConfig: SecurableType.COLUMN,
    VolumeConfig: SecurableType.VOLUME,
    FunctionConfig: SecurableType.FUNCTION,
}


def _securable_type_of(cfg: object) -> SecurableType | None:
    """Map a config class to its SecurableType."""
    return _CONFIG_CLASS_TO_SECURABLE_TYPE.get(type(cfg))


def _build_securables_dict(
    config: ResourcesConfig,
) -> dict[tuple[SecurableType, str], str]:
    """Map each configured securable, keyed by type and full name, to its file path."""
    result = {}
    for cfg in iter_securable_configs(config):
        if cfg.file_path:
            securable_type = _securable_type_of(cfg)
            if securable_type:
                result[(securable_type, cfg.full_name)] = cfg.file_path.as_posix()
    return result


def _attached_securable_type(policy: BasePolicyConfig) -> SecurableType:
    if policy.table_name:
        return SecurableType.TABLE
    if policy.schema_name:
        return SecurableType.SCHEMA
    return SecurableType.CATALOG


def _build_policies_dict(
    config: ResourcesConfig,
) -> dict[tuple[SecurableType, str, str], str]:
    """Map each mask/filter policy, keyed by the securable it is attached to and its
    name, to its config file path. Grant policies are attributed via privileges."""
    return {
        (
            _attached_securable_type(policy),
            policy.parent_full_name,
            policy.name,
        ): policy.file_path.as_posix()
        for policy in iter_policy_configs(config)
        if not isinstance(policy, GrantPolicyConfig) and policy.file_path is not None
    }


def _build_governed_tags_dict(config: ResourcesConfig) -> dict[str, str]:
    """Build a mapping of tag name → config file path."""
    result = {}
    for tag in (config.governed_tags or {}).values():
        if tag.file_path:
            result[tag.name] = tag.file_path.as_posix()
    return result


def _build_domains_dict(config: ResourcesConfig) -> dict[str, str]:
    """Build a mapping of domain governed_tag → config file path."""
    result = {}
    for domain in (config.domains or {}).values():
        if domain.file_path:
            result[domain.governed_tag] = domain.file_path.as_posix()
    return result


def _build_groups_dicts(
    config: ResourcesConfig,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build mappings of group id → path and group name → path.

    Returns (by_id, by_name). By id is used when group_id is set; by name otherwise.
    """
    by_id = {}
    by_name = {}
    for group in (config.groups or {}).values():
        if group.file_path:
            path = group.file_path.as_posix()
            if group.id:
                by_id[group.id] = path
            by_name[group.name] = path
    return by_id, by_name


def _build_privileges_dict(
    config: ResourcesConfig, state: ActualState, run_date: date
) -> dict[tuple[SecurableType, str, str, PrivilegeType], str]:
    """Map each privilege the active grant policies produce to the first producing
    policy's file path (see the module docstring). Privileges granted to a config
    principal that can't be resolved are skipped."""
    result = {}
    for policy_cfg, privileges in match_grant_policy_privileges(
        config, state.tags, run_date
    ):
        if policy_cfg.file_path is None:
            continue
        path = policy_cfg.file_path.as_posix()
        for privilege in privileges:
            principal_name = privilege.principal.name
            resolved = state.principals.get(principal_name)
            if resolved is None:
                continue
            key = (
                privilege.securable_type,
                privilege.securable_full_name,
                resolved.identifier,
                privilege.privilege_type,
            )
            result.setdefault(key, path)
    return result


@dataclass(frozen=True)
class ConfigPaths:
    """Lookups from a state object's identity to its config ``file_path``.

    Values are POSIX-format file paths or None when the object is absent from config.
    """

    _securables: dict[tuple[SecurableType, str], str]
    _policies: dict[tuple[SecurableType, str, str], str]
    _governed_tags: dict[str, str]
    _domains: dict[str, str]
    _groups_by_id: dict[str, str]
    _groups_by_name: dict[str, str]
    _privileges: dict[tuple[SecurableType, str, str, PrivilegeType], str]

    def securable(self, securable_type: SecurableType, full_name: str) -> str | None:
        """Look up a securable by type and full name."""
        return self._securables.get((securable_type, full_name))

    def policy(
        self, securable_type: SecurableType, securable_full_name: str, name: str
    ) -> str | None:
        """Look up a mask/filter policy by its attached securable and name."""
        return self._policies.get((securable_type, securable_full_name, name))

    def governed_tag(self, name: str) -> str | None:
        """Look up a governed tag by name."""
        return self._governed_tags.get(name)

    def domain(self, tag_key: str) -> str | None:
        """Look up a domain by its tag key."""
        return self._domains.get(tag_key)

    def group(self, display_name: str, group_id: str | None = None) -> str | None:
        """Look up a group by configured id first, then display name, so a group
        renamed in the account still matches its config."""
        if group_id:
            result = self._groups_by_id.get(group_id)
            if result:
                return result
        return self._groups_by_name.get(display_name)

    def privilege(self, privilege: SecurablePrivilege) -> str | None:
        """Look up the grant policy that produces an actual privilege, matched by
        its principal's canonical identifier."""
        return self._privileges.get(
            (
                privilege.securable_type,
                privilege.securable_full_name,
                privilege.principal.identifier,
                privilege.privilege_type,
            )
        )


def build_config_paths(
    config: ResourcesConfig, state: ActualState, run_date: date
) -> ConfigPaths:
    """Build the shared lookups for mapping state objects to their config file paths."""
    groups_by_id, groups_by_name = _build_groups_dicts(config)
    return ConfigPaths(
        _securables=_build_securables_dict(config),
        _policies=_build_policies_dict(config),
        _governed_tags=_build_governed_tags_dict(config),
        _domains=_build_domains_dict(config),
        _groups_by_id=groups_by_id,
        _groups_by_name=groups_by_name,
        _privileges=_build_privileges_dict(config, state, run_date),
    )
