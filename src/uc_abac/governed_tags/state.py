from __future__ import annotations

from dataclasses import dataclass, field

from uc_abac.principals import Principal


@dataclass(frozen=True)
class GovernedTag:
    """Desired or actual state of an account-level governed tag (tag policy).

    ``assigners`` is **authoritative only when supplied**, like group members and
    assumers: on the desired side ``None`` (the key omitted in config) leaves the
    tag's current assigners untouched, while a frozenset (including the empty one,
    which removes all) is reconciled exactly. Only the compiler sets ``None``; the
    default is an empty frozenset, which actual state always carries. The differ
    fills unmanaged desired assigners from actual before comparing, so a diff only
    ever holds frozensets.
    """

    name: str
    description: str = ""
    allowed_values: frozenset[str] = frozenset()
    assigners: frozenset[Principal] | None = frozenset()


@dataclass
class GovernedTagDiff:
    to_create: set[GovernedTag] = field(default_factory=set)
    to_update: set[GovernedTag] = field(default_factory=set)
    to_delete: set[GovernedTag] = field(default_factory=set)
    old_values: dict[str, GovernedTag] = field(default_factory=dict)
