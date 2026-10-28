from __future__ import annotations

import hashlib
import json
import re

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import CACHE_KIND_CLUSTERING, LLMCacheRepository
from curriculum_agent.llm import complete_clustering
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
    skipped = 0
    for i, raw in enumerate(names):
        norm = normalize_name(raw)
        if not norm:
            skipped += 1
            continue
        by_norm.setdefault(norm, []).append(i)
        display.setdefault(norm, raw.strip())
    if skipped:
        logger.warning(f"dedupe_names: skipped {skipped} blank/whitespace-only name(s)")
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
        keep: list[int] = []
        for i in indices:
            if not (0 <= i < n):
                out_of_range += 1
            elif i in seen:
                duplicates += 1
            else:
                seen.add(i)
                keep.append(i)
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


def _clustering_contract_fingerprint() -> str:
    """Short hash of everything that decides the SHAPE of a cached clustering.

    Mirrors the extraction cache's fingerprint, for the same reason: the key is
    otherwise just the input names plus the model, so changing a response schema
    or a prompt leaves old entries matching and silently replays a grouping
    produced under different instructions.
    """
    schemas = json.dumps(
        [
            ClusterAssignmentsResponse.model_json_schema(),
            MergeGroupsResponse.model_json_schema(),
        ],
        sort_keys=True,
    )
    # Only the system messages carry instructions; the user message is the name
    # list, which the key already covers. The clustering prompt is sampled twice
    # because half its instructions only appear when a program context is given:
    # sampling the context-free build alone would leave a reworded context rule
    # outside the hash, and entries produced under the old wording would keep
    # matching — the very defect this fingerprint exists to prevent. The sample
    # value is a placeholder; the real context is per-call and lives in the key.
    prompts = "\x00".join(
        [
            build_cluster_skills_prompt([])[0]["content"],
            build_cluster_skills_prompt([], None, "context sample")[0]["content"],
            build_merge_clusters_prompt([])[0]["content"],
        ]
    )
    return hashlib.sha256(f"{schemas}\x00{prompts}".encode()).hexdigest()[:16]


_CLUSTERING_CONTRACT = _clustering_contract_fingerprint()


def is_valid_partition(groups: list[list[int]], n: int) -> bool:
    """True when `groups` assigns every index below `n` exactly once.

    Freshly computed groupings go through `validate_assignments`, which repairs a
    malformed answer. A cached grouping bypasses that entirely — it is replayed
    raw — so an entry written by an older or buggier version could hand back an
    out-of-range index (an IndexError in the caller, which does `bucket[i]`) or a
    partial cover (skills silently vanishing). Checking on the way out keeps the
    cache from reintroducing a class of bug the compute path already guards.
    """
    seen: set[int] = set()
    for group in groups:
        for i in group:
            if not isinstance(i, int) or not (0 <= i < n) or i in seen:
                return False
            seen.add(i)
    return len(seen) == n


# Bounds the model's hidden reasoning on both clustering calls. Unbounded, GLM's
# reasoning took 234s on one 45-name S-bucket call on 2026-10-28 (375s on an
# earlier probe), against the 300s Agent 1 grouping budget. The bound is sent
# only to OpenRouter. `.claude/rules/llm-slots.md` notes this endpoint may treat
# any bound as reasoning off, so the grouping quality under the bound is still
# being measured.
_MAX_REASONING_TOKENS = 1024


async def _cluster_pass(
    names: list[str], target_clusters: int | None = None, program_context: str | None = None
) -> list[tuple[str, list[int]]]:
    """One call on the clustering slot over `names`, validated."""
    result = await complete_clustering(
        ClusterAssignmentsResponse,
        build_cluster_skills_prompt(names, target_clusters, program_context),
        temperature=0,
        reasoning_max_tokens=_MAX_REASONING_TOKENS,
    )
    return validate_assignments([(c.label_th, c.member_indices) for c in result.clusters], names)


async def _cluster_map_reduce(
    names: list[str], target_clusters: int | None = None, program_context: str | None = None
) -> list[list[int]]:
    """Cluster per batch, then merge equivalent cluster labels across batches.

    The target is applied at the merge, not per batch: a batch sees a slice of
    the bucket and is meant to over-produce, and the merge is where the final
    count is decided.
    """
    labelled: list[tuple[str, list[int]]] = []
    offset = 0
    for batch in split_batches(names):
        for label, indices in await _cluster_pass(batch, None, program_context):
            labelled.append((label, [offset + i for i in indices]))
        offset += len(batch)

    labels = [label for label, _ in labelled]
    merge = await complete_clustering(
        MergeGroupsResponse,
        build_merge_clusters_prompt(labels, target_clusters),
        temperature=0,
        reasoning_max_tokens=_MAX_REASONING_TOKENS,
    )
    merged = validate_assignments([("", g) for g in merge.groups], labels)
    return [sorted(i for ci in group for i in labelled[ci][1]) for _, group in merged]


async def cluster_skill_names(
    names: list[str], target_clusters: int | None = None, program_context: str | None = None
) -> list[list[int]]:
    """Group skill names by meaning on the clustering slot.

    Returns groups of indices into `names`. Single pass when the list fits in one
    prompt; batch + merge otherwise. Results are cached keyed on the full name
    list, the model, and a fingerprint of the response schemas and prompts, so
    re-runs on identical input are deterministic while a change to either
    contract invalidates the affected entries. A cached grouping that does not
    partition the names exactly once is discarded rather than trusted.

    `program_context` names the program these skills belong to, so the same names
    read against a different field group differently. It is in the key for the
    same reason `target_clusters` is.
    """
    if not names:
        return []
    if len(names) == 1:
        return [[0]]

    cache = LLMCacheRepository()
    # Order- and spelling-sensitive: callers should pass a deterministic
    # ordering (dedupe_names' sorted, first-seen-spelling output).
    # The target is in the key because it goes into the prompt: the contract
    # fingerprint covers only the instructions that do not vary per call, so
    # without this a bucket asked for four groups would be served an entry
    # produced when it was asked for eight. The program context is in the key on
    # the same grounds: it reaches the prompt, so two programs whose skill names
    # coincide must not share an entry.
    cache_key = hashlib.sha256(
        "\x00".join(
            [
                *names,
                settings.clustering_model,
                _CLUSTERING_CONTRACT,
                str(target_clusters),
                str(program_context),
            ]
        ).encode()
    ).hexdigest()
    cached = await cache.get(cache_key)
    if cached is not None and cached[0] == settings.clustering_model:
        try:
            groups = [[int(i) for i in g] for g in json.loads(cached[1])]
        except (TypeError, ValueError) as exc:
            logger.warning(f"Unreadable clustering cache entry, re-clustering: {exc}")
        else:
            if is_valid_partition(groups, len(names)):
                return groups
            logger.warning(
                f"Cached clustering does not partition {len(names)} names exactly once — "
                "discarding and re-clustering"
            )

    if len(names) <= SINGLE_PASS_MAX:
        groups = [
            indices for _, indices in await _cluster_pass(names, target_clusters, program_context)
        ]
    else:
        groups = await _cluster_map_reduce(names, target_clusters, program_context)

    await cache.set(
        cache_key,
        settings.clustering_model,
        json.dumps(groups),
        kind=CACHE_KIND_CLUSTERING,
        contract=_CLUSTERING_CONTRACT,
    )
    return groups
