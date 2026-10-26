"""
LangGraph state machine for the curriculum design agent.

Usage:
    from langgraph.checkpoint.sqlite import SqliteSaver
    from curriculum_agent.graph import build_graph

    saver = SqliteSaver.from_conn_string("checkpoints.db")
    graph = build_graph(checkpointer=saver)

    config = {"configurable": {"thread_id": "program-cs-2025"}}
    result = await graph.ainvoke({"program_id": "cs-2025"}, config)

    # Resume after HITL interrupt:
    await graph.aupdate_state(config, edited_state)
    await graph.ainvoke(None, config)
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, interrupt
from loguru import logger

# ----------------------------- State -----------------------------


class AgentState(TypedDict, total=False):
    program_id: str

    # Stage 0
    metadata: dict[str, Any]

    # Stage 1
    raw_evidence: list[dict[str, Any]]
    classified_evidence: list[dict[str, Any]]

    # Stage 2
    extracted_skills: list[dict[str, Any]]
    skill_groups: list[dict[str, Any]]
    needs: list[dict[str, Any]]
    dropped_ungrounded_count: int

    # Stage 3
    plos: list[dict[str, Any]]

    # Advisory PLO set review, written by the stage-06 node after the report. Nothing
    # in the graph reads it back; the page reads the stored row. None when no
    # review could be produced or kept (no PLOs, or a read or store failed).
    plo_review: dict[str, Any] | None

    # Stage 3 report — assembled by plo_report, keyed for designer drill-down.
    report: dict[str, Any]

    current_stage: str
    checkpoint_status: Literal["pending", "approved", "needs_revision"]
    designer_notes: str

    # Optional per-request guidance from the designer, read by the stages that
    # author prose. Deliberately not accumulated: each REST endpoint sets it from
    # its own request body, so a stage sees the note given to it and nothing
    # earlier. That is also why no `Annotated[..., reducer]` is needed — a reducer
    # is only required when two concurrent nodes write the same key.
    designer_note: str

    # Per-run switch for the SMART validation agent (POST /plos/run). Absent
    # means validate; only the REST route ever sets it, and only to False.
    run_validation: bool


# --------------------------- Stage nodes -------------------------


async def stage_0_intake(state: AgentState) -> AgentState:
    from curriculum_agent.stages.intake import run  # noqa: PLC0415

    return await run(state)


async def stage_1_stakeholder_needs(state: AgentState) -> AgentState:
    from curriculum_agent.stages.stakeholder_needs import run  # noqa: PLC0415

    return await run(state)


async def stage_2_skill_extraction(state: AgentState) -> AgentState:
    from curriculum_agent.stages.skill_extraction import run  # noqa: PLC0415

    return await run(state)


async def stage_2a_skill_grouping(state: AgentState) -> AgentState:
    from curriculum_agent.stages.skill_grouping import run  # noqa: PLC0415

    return await run(state)


async def stage_2b_need_combination(state: AgentState) -> AgentState:
    from curriculum_agent.stages.need_combination import run  # noqa: PLC0415

    return await run(state)


async def stage_3_plo_synthesis(state: AgentState) -> AgentState:
    from curriculum_agent.stages.plo_synthesis import run  # noqa: PLC0415

    return await run(state)


async def stage_6_plo_review(state: AgentState) -> AgentState:
    from curriculum_agent.stages.plo_review import run  # noqa: PLC0415

    return await run(state)


async def stage_5_plo_report(state: AgentState) -> AgentState:
    from curriculum_agent.stages.plo_report import run  # noqa: PLC0415

    return await run(state)


# -------------------- Human-in-the-loop nodes --------------------


def review_stakeholder_needs(state: AgentState) -> AgentState:
    payload = interrupt("Stage 1 complete — review classified evidence before clustering")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


async def review_needs(state: AgentState) -> AgentState:
    payload = interrupt("Stage 2 complete — review raw skills and distilled Needs")
    if isinstance(payload, dict):
        state = {**state, **payload}
    # The designer may have split a merged Need while suspended; the checkpoint
    # still holds the pre-split set, so reload what is stored now.
    from curriculum_agent.data.repositories import NeedRepository  # noqa: PLC0415

    active = await NeedRepository().list_active_by_program(state["program_id"])
    return {**state, "needs": [n.model_dump(mode="json") for n in active]}


def review_plos(state: AgentState) -> AgentState:
    payload = interrupt("Stage 3 complete — review/edit PLOs before PLO report")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


# ----------------------- Stages as reported ----------------------

# The stages a designer works through, in order. Fewer than the graph has nodes:
# skill_extraction and skill_grouping (Agent 1) report as skill_extraction, with
# no checkpoint of their own; need_combination (Agent 2) is need_analysis, and
# the review gate sits after it. Each is its own page and rail stage.
# This is the same list the UI keys its rail off — a value outside it reaches the
# frontend as "unknown stage" and the program looks like it never started.
DESIGNER_STAGES: tuple[str, ...] = (
    "intake",
    "stakeholder_needs",
    "skill_extraction",
    "need_analysis",
    "plo_synthesis",
    "plo_report",
    "plo_review",
)

# Which stage a suspended run is waiting at, by the node it is suspended on.
#
# Declared here beside the nodes it names rather than in the API layer that reads
# it: this map drifted once already, still holding a "review_clusters" node that
# had been renamed to "review_needs_node", which meant every run suspended after
# need_combination wrote the raw node name into sessions.current_stage and the UI
# read it as a program that had not started. test_session_stage_mapping.py checks
# both directions against the compiled graph so a rename cannot do that again.
REVIEW_NODE_STAGE: dict[str, str] = {
    "review_evidence": "stakeholder_needs",
    "review_needs_node": "need_analysis",
    "review_plos_node": "plo_synthesis",
}


def stage_reached(
    *,
    has_evidence: bool,
    has_skills: bool,
    has_needs: bool,
    has_plos: bool,
    has_current_review: bool = False,
) -> str:
    """The furthest stage a program has produced output for.

    Derived from what is stored rather than recorded as a program runs, because
    there are two ways to run a stage and only one of them was doing the
    recording. A graph session writes the stage it suspends at; the per-stage
    REST routes the stage pages call write nothing, so a designer working page by
    page had no recorded progress at all and the rail showed every stage as not
    yet reached. Deriving it means both paths report the same thing without
    either having to remember to.

    It also cannot go stale. Deleting a program's evidence, or re-running skill
    extraction, moves this answer back on its own; a stored column would keep
    claiming the furthest point the program ever got to.

    Skills alone answer `skill_extraction`; once Needs exist the answer is
    `need_analysis`. They are two pages: skills (Agent 1, no checkpoint) and
    Needs (Agent 2, where the review gate is).

    The report leaves no artifact of its own — it re-persists the PLOs synthesis
    already wrote — so a program that has been through it looks exactly like one
    that has not. The QA agent's review does leave one, and only a review current
    for the stored set counts: a stale one means the set changed after it was
    made, and the next thing to do is the report.
    """
    if has_current_review:
        return "plo_review"
    if has_plos:
        return "plo_synthesis"
    if has_needs:
        return "need_analysis"
    if has_skills:
        return "skill_extraction"
    if has_evidence:
        return "stakeholder_needs"
    # The program row itself is intake's output, so a program that exists has
    # always got at least this far.
    return "intake"


# --------------------------- Build graph -------------------------


def build_graph(
    checkpointer: Checkpointer = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    g = StateGraph(AgentState)

    g.add_node("intake", stage_0_intake)
    g.add_node("stakeholder_needs", stage_1_stakeholder_needs)
    g.add_node("review_evidence", review_stakeholder_needs)
    g.add_node("skill_extraction", stage_2_skill_extraction)
    g.add_node("skill_grouping", stage_2a_skill_grouping)
    g.add_node("need_combination", stage_2b_need_combination)
    g.add_node("review_needs_node", review_needs)
    g.add_node("plo_synthesis", stage_3_plo_synthesis)
    g.add_node("review_plos_node", review_plos)
    g.add_node("plo_report", stage_5_plo_report)
    g.add_node("plo_review", stage_6_plo_review)

    g.set_entry_point("intake")
    g.add_edge("intake", "stakeholder_needs")
    g.add_edge("stakeholder_needs", "review_evidence")
    g.add_edge("review_evidence", "skill_extraction")
    g.add_edge("skill_extraction", "skill_grouping")
    g.add_edge("skill_grouping", "need_combination")
    g.add_edge("need_combination", "review_needs_node")
    g.add_edge("review_needs_node", "plo_synthesis")
    g.add_edge("plo_synthesis", "review_plos_node")
    # No checkpoint after the PLOs (immutable rule 7, waived for this segment by
    # the designer, 2026-10-12): the report re-persists the approved set and the
    # QA agent only advises, so a checkpoint between or after them gates nothing.
    g.add_edge("review_plos_node", "plo_report")
    g.add_edge("plo_report", "plo_review")
    g.add_edge("plo_review", END)

    return g.compile(checkpointer=checkpointer)


# ------------------------ Thread lifecycle -----------------------


async def discard_thread(
    graph: CompiledStateGraph[AgentState, None, AgentState, AgentState],
    thread_id: str,
) -> bool:
    """Delete every checkpoint the saver holds for one thread.

    Checkpoint rows live in their own schema with no foreign key back to the
    application tables, so nothing removes them when a program is deleted or a
    session ends. That matters beyond disk: a suspended checkpoint holds a full
    copy of the AgentState — the program's evidence text, extracted skills,
    Needs and PLOs — and dropping the thread is the only thing that removes it.

    Never raises. It is called after the deletion the caller asked for has
    already committed, and failing the request then would report "not deleted"
    for something that is already gone. A failure is logged at ERROR instead,
    since leftover rows are a data-retention problem someone has to see.
    """
    # Falsy, not `is None`: LangGraph also spells "no checkpointer" as False on a
    # graph compiled with persistence explicitly disabled, and that would reach
    # the call below as an AttributeError logged at ERROR — noise for a graph
    # that never persisted anything to drop.
    checkpointer = getattr(graph, "checkpointer", None)
    if not checkpointer:
        logger.warning(f"No checkpointer configured — thread '{thread_id}' left in place")
        return False
    try:
        await checkpointer.adelete_thread(thread_id)
    except Exception as exc:
        logger.error(f"Could not discard checkpoint thread '{thread_id}': {exc}")
        return False
    logger.info(f"Discarded checkpoint thread '{thread_id}'")
    return True
