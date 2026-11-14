from __future__ import annotations

from uc_abac.configs import ResourcesConfig
from uc_abac.resources.governed_tags.state import GovernedTag
from uc_abac.resources.principals import compile_principal_names


def compile_desired_governed_tags(config: ResourcesConfig) -> set[GovernedTag]:
    """Produce the set of desired governed tags declared under resources.governed_tags.

    Each name in `assigners` becomes an unresolved Principal
    (principal_type=UNKNOWN, name=<display_name>); the differ resolves them
    against the workspace before comparing against actual state. Omitted
    assigners stay ``None`` (unmanaged); an explicit ``[]`` compiles to an empty
    frozenset (remove all).
    """
    if not config.governed_tags:
        return set()
    return {
        GovernedTag(
            name=gt.name,
            description=gt.description or "",
            allowed_values=frozenset(gt.allowed_values or ()),
            assigners=compile_principal_names(gt.assigners),
        )
        for gt in config.governed_tags.values()
    }
