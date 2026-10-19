"""Structural fingerprints of JSON documents.

The watch does not care what Fresha's pages say, only whether they still say
it in the same shape: the same keys, nested the same way. A shape is a sorted
list of leaf paths, each tagged with a coarse kind:

    employeeProfiles.edges[].node.displayName:value
    employeeProfiles.edges[].node.avatar:object
    screenServices.categories[].items:list

Every element of a list is merged into one "[]" entry, so a longer team or a
new service is not a change. Strings, numbers, booleans and null are all just
"value", so a field that is sometimes null does not flap. Only keys appearing
or disappearing, or a value turning into an object or list, count.
"""
from __future__ import annotations

import hashlib


def paths(value, *, prefix: str = "", max_depth: int = 8) -> list[str]:
    """Sorted leaf paths of a JSON-like value."""
    found: set[str] = set()
    _walk(value, prefix, 0, max_depth, found)
    return sorted(found)


def _walk(value, prefix: str, depth: int, max_depth: int, found: set[str]) -> None:
    if isinstance(value, dict):
        if depth >= max_depth or not value:
            found.add(f"{prefix}:object")
            return
        for key, child in value.items():
            _walk(child, f"{prefix}.{key}" if prefix else str(key), depth + 1, max_depth, found)
    elif isinstance(value, list):
        found.add(f"{prefix}:list")
        if depth >= max_depth:
            return
        for child in value:
            _walk(child, f"{prefix}[]", depth + 1, max_depth, found)
    else:
        found.add(f"{prefix}:value")


def fingerprint(leaf_paths: list[str]) -> str:
    return hashlib.sha256("\n".join(leaf_paths).encode("utf-8")).hexdigest()[:12]


def describe(old: list[str], new: list[str], limit: int = 12) -> list[str]:
    """Human-readable difference between two shapes. Empty means identical."""
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    lines = [f"removed {p}" for p in removed] + [f"added {p}" for p in added]
    if len(lines) > limit:
        lines = lines[:limit] + [f"... and {len(lines) - limit} more"]
    return lines
