from __future__ import annotations

from datetime import datetime, timedelta

from curriculum_agent.data.prune_cache import (
    CLUSTERING,
    EXTRACTION,
    LIVE,
    ORPHANED_KIND,
    STALE_CONTRACT,
    STALE_MODEL,
    CacheRow,
    classify_rows,
    select_expired,
)

_NOW = datetime(2026, 8, 30, 12, 0, 0)

# What each kind currently resolves to. Extraction and clustering deliberately
# sit on different models here — that is the shipped arrangement, and it is the
# whole reason a row carries its kind.
_LIVE_BY_KIND = {
    EXTRACTION: ("typhoon-v2.5-30b-a3b-instruct", "aaaa111122223333"),
    CLUSTERING: ("meta-llama/llama-3.3-70b-instruct", "bbbb444455556666"),
}


def _row(
    kind: str,
    model: str,
    contract: str,
    *,
    evidence_hash: str = "hash",
    created_at: datetime = _NOW,
) -> CacheRow:
    return CacheRow(
        evidence_hash=evidence_hash,
        kind=kind,
        model=model,
        contract=contract,
        created_at=created_at,
    )


def test_a_row_matching_its_kinds_model_and_contract_is_live():
    row = _row(EXTRACTION, *_LIVE_BY_KIND[EXTRACTION])

    assert classify_rows([row], _LIVE_BY_KIND)[LIVE] == [row]


def test_a_row_written_by_a_model_the_kind_no_longer_uses_is_stale():
    """The case that produced this tool: moving a slot to another provider makes
    every entry it ever wrote unreachable, since the model name is inside the
    key."""
    row = _row(EXTRACTION, "meta-llama/llama-3.3-70b-instruct", "aaaa111122223333")

    assert classify_rows([row], _LIVE_BY_KIND)[STALE_MODEL] == [row]


def test_a_row_written_under_an_older_contract_is_stale():
    """Editing a prompt or a response schema moves the fingerprint, so the key
    moves with it. Without the column this row is indistinguishable from a live
    one — it just never gets hit again."""
    row = _row(EXTRACTION, "typhoon-v2.5-30b-a3b-instruct", "0000dead0000beef")

    assert classify_rows([row], _LIVE_BY_KIND)[STALE_CONTRACT] == [row]


def test_a_row_whose_kind_no_longer_exists_is_reported_as_its_own_class():
    """Not folded into stale-model: nothing is reading this kind at all, so
    naming it after a model mismatch would describe the wrong cause."""
    row = _row("summarisation", "some-model", "aaaa111122223333")

    assert classify_rows([row], _LIVE_BY_KIND)[ORPHANED_KIND] == [row]


def test_each_kind_is_judged_against_its_own_slot():
    """The reason `kind` is a column. Both rows carry a model that is live for
    the pipeline as a whole; each is stale for the kind that wrote it."""
    swapped_extraction = _row(
        EXTRACTION,
        *_LIVE_BY_KIND[CLUSTERING],
        evidence_hash="e1",
    )
    swapped_clustering = _row(
        CLUSTERING,
        *_LIVE_BY_KIND[EXTRACTION],
        evidence_hash="c1",
    )

    grouped = classify_rows([swapped_extraction, swapped_clustering], _LIVE_BY_KIND)

    assert grouped[STALE_MODEL] == [swapped_extraction, swapped_clustering]
    assert grouped[LIVE] == []


def test_every_class_is_present_even_when_empty():
    """The caller reports counts per class; a missing key would be a KeyError in
    the report rather than a zero."""
    grouped = classify_rows([], _LIVE_BY_KIND)

    assert set(grouped) == {LIVE, STALE_MODEL, STALE_CONTRACT, ORPHANED_KIND}
    assert all(rows == [] for rows in grouped.values())


def test_expiry_is_orthogonal_to_the_classes_and_reaches_live_rows():
    """--older-than exists for the garbage no column can detect: evidence text
    edited in place, a program renamed or moved to another field, a program
    deleted. Those rows look live, so the age filter has to be able to take
    them — which is why it is a separate flag."""
    live_but_old = _row(
        EXTRACTION,
        *_LIVE_BY_KIND[EXTRACTION],
        evidence_hash="old",
        created_at=_NOW - timedelta(days=40),
    )
    live_and_recent = _row(
        EXTRACTION,
        *_LIVE_BY_KIND[EXTRACTION],
        evidence_hash="new",
        created_at=_NOW - timedelta(days=5),
    )

    expired = select_expired([live_but_old, live_and_recent], _NOW - timedelta(days=30))

    assert expired == [live_but_old]


def test_a_row_exactly_on_the_cutoff_survives():
    """Strictly older, so `--older-than 30` twice in a row is stable rather than
    dependent on the second the sweep happened to run at."""
    on_the_line = _row(EXTRACTION, *_LIVE_BY_KIND[EXTRACTION], created_at=_NOW - timedelta(days=30))

    assert select_expired([on_the_line], _NOW - timedelta(days=30)) == []
