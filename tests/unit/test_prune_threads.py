from __future__ import annotations

from curriculum_agent.data.prune_threads import LIVE, ORPHANED, REJECTED, classify_threads


def test_a_thread_named_for_a_live_program_is_live() -> None:
    """create_program runs the graph under the program id itself, so this thread
    exists for every program, including ones no session ever ran on."""
    grouped = classify_threads(["cs"], {"cs"}, {})

    assert grouped[LIVE] == ["cs"]
    assert grouped[ORPHANED] == []


def test_a_thread_whose_program_is_gone_is_orphaned() -> None:
    grouped = classify_threads(["deleted-program"], {"cs"}, {})

    assert grouped[ORPHANED] == ["deleted-program"]


def test_a_thread_whose_session_row_is_gone_is_orphaned() -> None:
    """delete_cascade removes the session rows, and the thread id lives on those
    rows — after the cascade nothing names this thread but the checkpointer."""
    grouped = classify_threads(["cs:s-old"], {"cs"}, {})

    assert grouped[ORPHANED] == ["cs:s-old"]


def test_a_running_session_thread_is_left_alone() -> None:
    grouped = classify_threads(["cs:s1"], {"cs"}, {"cs:s1": "suspended"})

    assert grouped[LIVE] == ["cs:s1"]
    assert grouped[REJECTED] == []


def test_a_rejected_session_thread_is_reported_separately_from_orphans() -> None:
    """Its session row is still there, so it is not orphaned — but rejection is
    terminal, retrying means a new thread_id, and nothing will resume this one."""
    grouped = classify_threads(["cs:s1"], {"cs"}, {"cs:s1": "rejected"})

    assert grouped[REJECTED] == ["cs:s1"]
    assert grouped[ORPHANED] == []
    assert grouped[LIVE] == []


def test_a_session_thread_outranks_a_program_id_of_the_same_name() -> None:
    """Contrived, but the lookup order has to be decided somewhere: a recorded
    session status is direct evidence about this thread, a program id match is
    inference from the naming scheme."""
    grouped = classify_threads(["cs"], {"cs"}, {"cs": "rejected"})

    assert grouped[REJECTED] == ["cs"]


def test_every_stored_thread_lands_in_exactly_one_group() -> None:
    stored = ["cs", "cs:s1", "cs:s2", "gone", "gone:s9"]
    grouped = classify_threads(
        stored, {"cs"}, {"cs:s1": "completed", "cs:s2": "rejected", "gone:s9": "rejected"}
    )

    assert sorted(grouped[LIVE] + grouped[ORPHANED] + grouped[REJECTED]) == sorted(stored)
    assert grouped[LIVE] == ["cs", "cs:s1"]
    assert grouped[ORPHANED] == ["gone"]
    assert grouped[REJECTED] == ["cs:s2", "gone:s9"]
