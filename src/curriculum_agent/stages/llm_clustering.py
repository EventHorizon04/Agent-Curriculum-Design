from __future__ import annotations

import re

from loguru import logger

SINGLE_PASS_MAX = 150
BATCH_SIZE = 100

_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercase, trim, collapse internal whitespace."""
    return _WS.sub(" ", name.strip()).lower()


def dedupe_names(names: list[str]) -> tuple[list[str], list[list[int]]]:
    """Collapse duplicate skill names by normalized form.

    Returns (unique_names, groups). unique_names is sorted by normalized form
    so prompts and cache keys are deterministic regardless of input order;
    groups[i] lists the indices in `names` that normalize to unique_names[i].
    The first-seen raw spelling (trimmed) is kept as the display name.
    """
    by_norm: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    for i, raw in enumerate(names):
        norm = normalize_name(raw)
        by_norm.setdefault(norm, []).append(i)
        display.setdefault(norm, raw.strip())
    ordered = sorted(by_norm)
    return [display[k] for k in ordered], [by_norm[k] for k in ordered]


def split_batches(items: list[str], size: int = BATCH_SIZE) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def validate_assignments(
    clusters: list[tuple[str, list[int]]], names: list[str]
) -> list[tuple[str, list[int]]]:
    """Enforce that every index into `names` is assigned exactly once.

    Out-of-range and already-assigned indices are dropped; indices the LLM
    never assigned become singleton clusters labeled with the skill name —
    skills are never silently dropped.
    """
    n = len(names)
    seen: set[int] = set()
    dropped = 0
    cleaned: list[tuple[str, list[int]]] = []
    for label, indices in clusters:
        keep = [i for i in indices if 0 <= i < n and i not in seen]
        dropped += len(indices) - len(keep)
        seen.update(keep)
        if keep:
            cleaned.append((label, keep))
    missing = [i for i in range(n) if i not in seen]
    cleaned.extend((names[i], [i]) for i in missing)
    if dropped:
        logger.warning(f"LLM clustering: dropped {dropped} invalid/duplicate indices")
    if missing:
        logger.warning(
            f"LLM clustering: {len(missing)} skills unassigned — added as singletons"
        )
    return cleaned
