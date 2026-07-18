from __future__ import annotations

import hashlib
import json
import re

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import LLMCacheRepository
from curriculum_agent.llm import complete_heavy
from curriculum_agent.prompts.cluster_skills import (
    build_cluster_skills_prompt,
    build_merge_clusters_prompt,
)

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
    The first-seen raw spelling (trimmed) is kept as the display name. Names
    that normalize to an empty string (blank/whitespace-only) are skipped.
    """
    by_norm: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    for i, raw in enumerate(names):
        norm = normalize_name(raw)
        if not norm:
            continue
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
    out_of_range = 0
    duplicates = 0
    cleaned: list[tuple[str, list[int]]] = []
    for label, indices in clusters:
        keep = [i for i in indices if 0 <= i < n and i not in seen]
        for i in indices:
            if not (0 <= i < n):
                out_of_range += 1
            elif i in seen:
                duplicates += 1
        seen.update(keep)
        if keep:
            cleaned.append((label, keep))
    missing = [i for i in range(n) if i not in seen]
    cleaned.extend((names[i], [i]) for i in missing)
    if out_of_range or duplicates:
        logger.warning(
            f"LLM clustering: dropped {out_of_range} out-of-range and "
            f"{duplicates} duplicate indices"
        )
    if missing:
        logger.warning(f"LLM clustering: {len(missing)} skills unassigned — added as singletons")
    return cleaned


class ClusterAssignment(BaseModel):
    label_th: str
    member_indices: list[int] = Field(default_factory=list)


class ClusterAssignmentsResponse(BaseModel):
    clusters: list[ClusterAssignment]


class MergeGroupsResponse(BaseModel):
    groups: list[list[int]]


async def _cluster_pass(names: list[str]) -> list[tuple[str, list[int]]]:
    """One heavy-model clustering call over `names`, validated."""
    result = await complete_heavy(
        ClusterAssignmentsResponse,
        build_cluster_skills_prompt(names),
        temperature=0,
    )
    return validate_assignments([(c.label_th, c.member_indices) for c in result.clusters], names)


async def _cluster_map_reduce(names: list[str]) -> list[list[int]]:
    """Cluster per batch, then merge equivalent cluster labels across batches."""
    labelled: list[tuple[str, list[int]]] = []
    offset = 0
    for batch in split_batches(names):
        for label, indices in await _cluster_pass(batch):
            labelled.append((label, [offset + i for i in indices]))
        offset += len(batch)

    labels = [label for label, _ in labelled]
    merge = await complete_heavy(
        MergeGroupsResponse,
        build_merge_clusters_prompt(labels),
        temperature=0,
    )
    merged = validate_assignments([("", g) for g in merge.groups], labels)
    return [sorted(i for ci in group for i in labelled[ci][1]) for _, group in merged]


async def cluster_skill_names(names: list[str]) -> list[list[int]]:
    """Group skill names by meaning using the heavy model.

    Returns groups of indices into `names`. Single pass when the list fits in
    one prompt; batch + merge otherwise. Results are cached keyed on the full
    name list + model, so re-runs on identical input are deterministic.
    """
    if not names:
        return []
    if len(names) == 1:
        return [[0]]

    cache = LLMCacheRepository()
    # Order- and spelling-sensitive: callers should pass a deterministic
    # ordering (dedupe_names' sorted, first-seen-spelling output).
    cache_key = hashlib.sha256("\x00".join([*names, settings.heavy_model]).encode()).hexdigest()
    cached = await cache.get(cache_key)
    if cached is not None and cached[0] == settings.heavy_model:
        return [[int(i) for i in g] for g in json.loads(cached[1])]

    if len(names) <= SINGLE_PASS_MAX:
        groups = [indices for _, indices in await _cluster_pass(names)]
    else:
        groups = await _cluster_map_reduce(names)

    await cache.set(cache_key, settings.heavy_model, json.dumps(groups))
    return groups
