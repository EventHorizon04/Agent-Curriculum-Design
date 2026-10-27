from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import need_dedup as nd
from curriculum_agent.stages.need_dedup import (
    DedupAnswer,
    DuplicateGroup,
    accept_groups,
    find_duplicate_groups,
    label_needs,
)

_METADATA = ProgramMetadata.model_validate(
    {
        "program_id": "test",
        "field": "ภาษาจีน",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "มนุษยศาสตร์",
        "university": "Test University",
    }
)


def _need(nid: str, *, ksec: KSECCategory = KSECCategory.S, demand: float = 0.5) -> Need:
    return Need(
        need_id=nid,
        program_id="test",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
    )


def _answer(*groups: list[str]) -> DedupAnswer:
    return DedupAnswer(groups=[DuplicateGroup(labels=g, reason_th="งานเดียวกัน") for g in groups])


def _ids(folds: list[nd.FoldGroup]) -> list[list[str]]:
    return [[n.need_id for n in f.needs] for f in folds]


# --------------------------- labelling ---------------------------


def test_labels_follow_the_given_order() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c")])

    assert {label: n.need_id for label, n in labelled.items()} == {"N1": "a", "N2": "b", "N3": "c"}


# --------------------------- accept_groups ---------------------------


def test_a_valid_pair_is_accepted_with_its_reason() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c")])

    (fold,) = accept_groups(_answer(["N1", "N3"]), labelled)

    assert [n.need_id for n in fold.needs] == ["a", "c"]
    assert fold.reason_th == "งานเดียวกัน"


def test_members_come_back_in_label_order_whatever_order_the_model_wrote() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c")])

    assert _ids(accept_groups(_answer(["N3", "N1"]), labelled)) == [["a", "c"]]


def test_labels_are_matched_after_trimming_and_uppercasing() -> None:
    labelled = label_needs([_need("a"), _need("b")])

    assert _ids(accept_groups(_answer([" n1", "N2 "]), labelled)) == [["a", "b"]]


def test_unknown_labels_are_removed_before_counting() -> None:
    """N9 does not exist: what is left is one Need, which is not a group."""
    labelled = label_needs([_need("a"), _need("b")])

    assert accept_groups(_answer(["N1", "N9"]), labelled) == []


def test_a_repeated_label_counts_once() -> None:
    labelled = label_needs([_need("a"), _need("b")])

    assert accept_groups(_answer(["N1", "N1"]), labelled) == []


def test_a_need_already_in_an_accepted_group_drops_the_later_group_whole() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c"), _need("d")])

    folds = accept_groups(_answer(["N1", "N2"], ["N2", "N3", "N4"]), labelled)

    assert _ids(folds) == [["a", "b"]], "the second group is dropped, not trimmed to N3+N4"


def test_mixed_ksec_group_accepted() -> None:
    """A K Need and an S Need that ask for one capability fold into one multi-tag Need."""
    labelled = label_needs([_need("a", ksec=KSECCategory.K), _need("b", ksec=KSECCategory.S)])

    assert _ids(accept_groups(_answer(["N1", "N2"]), labelled)) == [["a", "b"]]


def test_group_of_five_accepted_six_dropped() -> None:
    labelled = label_needs([_need(x) for x in "abcdef"])

    assert _ids(accept_groups(_answer(["N1", "N2", "N3", "N4", "N5"]), labelled)) == [
        ["a", "b", "c", "d", "e"]
    ]
    assert accept_groups(_answer(["N1", "N2", "N3", "N4", "N5", "N6"]), labelled) == []
    assert nd.MAX_GROUP_SIZE == 5


def test_a_dropped_group_does_not_reserve_its_members() -> None:
    """Only an *accepted* group takes its members: a group dropped for size
    must not stop a later, valid group from using one of them."""
    labelled = label_needs([_need(x) for x in "abcdefg"])

    folds = accept_groups(_answer(["N1", "N2", "N3", "N4", "N5", "N6"], ["N1", "N7"]), labelled)

    assert _ids(folds) == [["a", "g"]]


def test_an_empty_answer_accepts_nothing() -> None:
    assert accept_groups(DedupAnswer(), label_needs([_need("a"), _need("b")])) == []


def test_the_answer_is_summarised_in_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accepted and dropped counts, for the per-stage figures a study reports."""
    logger = Mock()
    monkeypatch.setattr(nd, "logger", logger)
    labelled = label_needs([_need("a"), _need("b"), _need("c")])

    accept_groups(_answer(["N1", "N2"], ["N2", "N3"]), labelled)

    lines = [c.args[0] for c in logger.info.call_args_list]
    assert "need_dedup: 1 group(s) accepted, 1 dropped by rule" in lines


# --------------------------- find_duplicate_groups ---------------------------


async def test_the_call_is_mapped_back_to_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value=_answer(["N2", "N1"]))
    monkeypatch.setattr(nd, "complete_need_dedup", call)

    folds = await find_duplicate_groups([_need("a"), _need("b"), _need("c")], _METADATA)

    assert _ids(folds) == [["a", "b"]]
    messages = call.await_args.args[1]
    user = messages[-1]["content"]
    assert "N1 | S | " in user and "need_id" not in user
    assert "สาขาภาษาจีน" in user, "the program context line reaches the prompt"
    assert call.await_args.kwargs["temperature"] == 0


async def test_the_kill_switch_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value=_answer(["N1", "N2"]))
    monkeypatch.setattr(nd, "complete_need_dedup", call)
    monkeypatch.setattr(nd.settings, "need_dedup_provider", "")

    folds = await find_duplicate_groups([_need("a"), _need("b")], _METADATA)
    assert folds == []
    assert folds.call == "disabled"
    call.assert_not_awaited()


async def test_fewer_than_two_needs_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value=DedupAnswer())
    monkeypatch.setattr(nd, "complete_need_dedup", call)

    assert await find_duplicate_groups([_need("a")], _METADATA) == []
    call.assert_not_awaited()


async def test_a_failing_call_folds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The step can only fold; its absence is the behaviour before it existed,
    so an outage costs duplicates and never a PLO."""
    monkeypatch.setattr(nd, "complete_need_dedup", AsyncMock(side_effect=RuntimeError("down")))

    folds = await find_duplicate_groups([_need("a"), _need("b")], _METADATA)
    assert folds == []
    assert folds.call == "failed"
