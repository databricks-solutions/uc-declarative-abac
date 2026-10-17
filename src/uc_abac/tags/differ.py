from __future__ import annotations

from uc_abac.tags.state import (
    SecurableTag,
    TagDiff,
)
from uc_abac.utils import Scope


def _tag_key(tag: SecurableTag) -> tuple:
    """Extract the unique key for a tag: (type, full_name, tag_name).

    Used across differ functions to group tags by identity and distinguish
    adds, updates, and removals based on which keys are present in desired
    vs actual state.
    """
    return (tag.securable_type, tag.securable_full_name, tag.tag_name)


def filter_retained_removals(
    diff: TagDiff,
    retain_prefixes: frozenset[str],
) -> tuple[TagDiff, set[SecurableTag]]:
    """Strip removals whose tag key starts with any retained prefix.

    Returns a new ``TagDiff`` whose ``to_remove`` excludes any tag whose
    ``tag_name`` starts with one of ``retain_prefixes``, together with the set
    of tags that were retained. ``to_add``, ``to_update`` and ``old_values`` are
    carried through untouched — retention only blocks removals, never additions
    or updates. An empty ``retain_prefixes`` is a no-op (the diff is returned
    unchanged and nothing is retained).
    """
    if not retain_prefixes:
        return diff, set()

    retained = {
        tag
        for tag in diff.to_remove
        if any(tag.tag_name.startswith(prefix) for prefix in retain_prefixes)
    }
    if not retained:
        return diff, set()

    new_diff = TagDiff(
        to_add=diff.to_add,
        to_update=diff.to_update,
        to_remove=diff.to_remove - retained,
        old_values=diff.old_values,
    )
    return new_diff, retained


def compute_tag_diff(desired: set[SecurableTag], actual: set[SecurableTag]) -> TagDiff:
    """Compute the diff between desired and actual tags.

    Compares on (securable_type, securable_full_name, tag_name):
    - to_add: tag key not present in actual
    - to_update: tag key present in both but value differs (desired value shown)
    - to_remove: tag key present in actual but absent from desired
    """
    desired_by_key = {_tag_key(t): t for t in desired}
    actual_by_key = {_tag_key(t): t for t in actual}

    desired_keys = desired_by_key.keys()
    actual_keys = actual_by_key.keys()

    to_add = {desired_by_key[k] for k in desired_keys - actual_keys}
    to_remove = {actual_by_key[k] for k in actual_keys - desired_keys}
    update_keys = {
        k
        for k in desired_keys & actual_keys
        if desired_by_key[k].tag_value != actual_by_key[k].tag_value
    }
    to_update = {desired_by_key[k] for k in update_keys}
    old_values = {k: actual_by_key[k].tag_value for k in update_keys}

    return TagDiff(
        to_add=to_add, to_update=to_update, to_remove=to_remove, old_values=old_values
    )


def filter_unmanaged_removals(
    diff: TagDiff,
    management_scope: Scope,
) -> tuple[TagDiff, set[SecurableTag]]:
    """Filter removals to those within the management scope.

    Under --tag-assignment-scopes, securables outside --tag-management-scopes
    never have tags removed. Returns a new TagDiff with to_remove limited to
    tags whose securable_full_name matches the management_scope, together with
    the set of tags that were dropped (not removed). to_add, to_update and
    old_values are carried through unchanged — only to_remove is filtered.
    """
    dropped = {
        tag
        for tag in diff.to_remove
        if not management_scope.matches(tag.securable_full_name)
    }
    if not dropped:
        return diff, set()

    new_diff = TagDiff(
        to_add=diff.to_add,
        to_update=diff.to_update,
        to_remove=diff.to_remove - dropped,
        old_values=diff.old_values,
    )
    return new_diff, dropped


def project_tag_state(actual: set[SecurableTag], diff: TagDiff) -> set[SecurableTag]:
    """Compute the post-run tag state after applying a diff to actual tags.

    The projected state includes: actual tags whose _tag_key is not in the
    removed or updated keys, plus all tags in to_add and to_update. This
    reflects what UC will hold after the run, including tags kept by retained
    prefixes or the assignment-only scope, used for grant-policy matching.
    """
    removed_and_updated_keys = {
        _tag_key(tag) for tag in diff.to_remove | diff.to_update
    }
    kept_actual = {
        tag for tag in actual if _tag_key(tag) not in removed_and_updated_keys
    }
    return kept_actual | diff.to_add | diff.to_update
