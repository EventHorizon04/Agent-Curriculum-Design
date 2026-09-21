"""Find and drop LLM cache rows nothing will ever read again.

`llm_cache` is keyed on a hash of everything that decides the answer — the input
text, the model, and a fingerprint of the prompt and response schema. That makes
a stale entry harmless (it is simply never hit) and permanent (nothing deletes
it). Switch a slot to another provider, or edit a prompt, and every row written
before the change becomes weight the table carries forever.

    uv run python -m curriculum_agent.data.prune_cache                  # report only
    uv run python -m curriculum_agent.data.prune_cache --delete
    uv run python -m curriculum_agent.data.prune_cache --older-than 30 --delete

Reporting is the default because the report is the review step, and because a
"stale" row is only stale against the *current* configuration: switch a provider
back and every row it wrote is live again. Deleting costs a re-run's worth of
tokens, so read the list first.

`--older-than` is a separate flag rather than part of --delete because it reaches
live rows. It is the only sweep for the garbage no column can detect: evidence
text edited in place, a program renamed or moved to another field (both are in
the extraction key), or a program deleted outright.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    CACHE_KIND_CLUSTERING,
    CACHE_KIND_EXTRACTION,
    LLMCacheRepository,
)

# Bound locally so the classes below read as one vocabulary. complete_light is
# absent on purpose: nothing caches it, so light_model never appears in a row
# and must never be counted as a live target.
EXTRACTION = CACHE_KIND_EXTRACTION
CLUSTERING = CACHE_KIND_CLUSTERING

LIVE = "live"
STALE_MODEL = "stale-model"
STALE_CONTRACT = "stale-contract"
ORPHANED_KIND = "orphaned-kind"

_UNREACHABLE = (STALE_MODEL, STALE_CONTRACT, ORPHANED_KIND)


@dataclass(frozen=True)
class CacheRow:
    """The columns the sweep reasons about. Deliberately not the ORM row: the
    payload is the bulk of the table and none of the classification depends on
    it, so keeping it out makes the whole thing a pure function over small
    values."""

    evidence_hash: str
    kind: str
    model: str
    contract: str
    created_at: datetime


def live_targets() -> dict[str, tuple[str, str]]:
    """What each kind resolves to right now: kind -> (model, contract).

    The contract fingerprints are imported here rather than at module scope
    because computing them loads the prompt builders and the response schemas —
    work a --help run has no use for.
    """
    from curriculum_agent.stages.llm_clustering import _CLUSTERING_CONTRACT
    from curriculum_agent.stages.skill_extraction import _EXTRACTION_CONTRACT

    return {
        EXTRACTION: (settings.extraction_model, _EXTRACTION_CONTRACT),
        CLUSTERING: (settings.clustering_model, _CLUSTERING_CONTRACT),
    }


def classify_rows(
    rows: Iterable[CacheRow],
    live_by_kind: dict[str, tuple[str, str]],
) -> dict[str, list[CacheRow]]:
    """Sort rows into live and three kinds of unreachable.

    Each row is judged against the slot *its own kind* resolves to, which is why
    the kind is stored at all: extraction and clustering sit on different models
    in the shipped configuration, so a single "is this the current model" check
    would call half the table stale.

    The three unreachable classes are separated because they have different
    causes and different lifetimes. A stale-model row comes back to life if the
    provider is switched back; a stale-contract row never does, because the
    prompt that produced it is gone from the source tree; an orphaned-kind row
    was written by a caller that no longer exists at all.
    """
    grouped: dict[str, list[CacheRow]] = {
        LIVE: [],
        STALE_MODEL: [],
        STALE_CONTRACT: [],
        ORPHANED_KIND: [],
    }
    for row in rows:
        target = live_by_kind.get(row.kind)
        if target is None:
            grouped[ORPHANED_KIND].append(row)
        elif row.model != target[0]:
            grouped[STALE_MODEL].append(row)
        elif row.contract != target[1]:
            grouped[STALE_CONTRACT].append(row)
        else:
            grouped[LIVE].append(row)
    return grouped


def select_expired(rows: Iterable[CacheRow], cutoff: datetime) -> list[CacheRow]:
    """Rows first computed strictly before `cutoff`, whatever their class.

    Strictly, so that running the same `--older-than N` twice is stable rather
    than depending on the second the sweep started at.
    """
    return [row for row in rows if row.created_at < cutoff]


def _report(grouped: dict[str, list[CacheRow]], expired: list[CacheRow]) -> None:
    total = sum(len(rows) for rows in grouped.values())
    logger.info(
        f"{total} cache row(s): {len(grouped[LIVE])} live, "
        f"{len(grouped[STALE_MODEL])} stale-model, "
        f"{len(grouped[STALE_CONTRACT])} stale-contract, "
        f"{len(grouped[ORPHANED_KIND])} orphaned-kind"
    )
    # Grouped by (kind, model, contract) rather than listed per row: a corpus
    # produces one row per evidence window, so the per-row list is thousands of
    # hashes long and says nothing the grouping does not.
    for label in _UNREACHABLE:
        buckets: dict[tuple[str, str, str], int] = {}
        for row in grouped[label]:
            key = (row.kind, row.model, row.contract)
            buckets[key] = buckets.get(key, 0) + 1
        for (kind, model, contract), count in sorted(buckets.items()):
            logger.info(f"  {label}: {count} row(s) from {kind} on {model} (contract {contract})")
    if expired:
        live = set(grouped[LIVE])
        live_expired = sum(1 for row in expired if row in live)
        logger.info(f"  expired: {len(expired)} row(s), of which {live_expired} otherwise live")


async def prune(delete: bool, older_than_days: int | None) -> dict[str, list[CacheRow]]:
    """Classify every cached row, and drop the doomed ones when asked."""
    repo = LLMCacheRepository()
    rows = [
        CacheRow(
            evidence_hash=r.evidence_hash,
            kind=r.kind,
            model=r.model,
            contract=r.contract,
            created_at=r.created_at,
        )
        for r in await repo.all_rows()
    ]
    grouped = classify_rows(rows, live_targets())
    expired = (
        select_expired(rows, datetime.utcnow() - timedelta(days=older_than_days))
        if older_than_days is not None
        else []
    )
    _report(grouped, expired)

    # A row can be both stale and expired; the set collapses that so the count
    # reported as deleted matches the number of rows that actually go.
    doomed = {row.evidence_hash for label in _UNREACHABLE for row in grouped[label]}
    doomed |= {row.evidence_hash for row in expired}
    if not doomed:
        logger.info("Nothing to prune")
        return grouped
    if not delete:
        logger.warning(f"{len(doomed)} row(s) would be deleted — re-run with --delete")
        return grouped

    deleted = await repo.delete_hashes(sorted(doomed))
    logger.info(f"Pruned {deleted} cache row(s)")
    return grouped


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="prune_cache",
        description="Report, and optionally drop, unreachable llm_cache rows.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="actually delete; without it the run only reports",
    )
    parser.add_argument(
        "--older-than",
        type=int,
        metavar="DAYS",
        help=(
            "also take rows first computed more than DAYS ago, including rows "
            "that are otherwise live"
        ),
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    # psycopg refuses a ProactorEventLoop, which is what asyncio.run builds on
    # Windows by default. Same reason api/__main__.py names its loop factory.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(prune(delete=args.delete, older_than_days=args.older_than))


if __name__ == "__main__":
    main()
