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

from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt


# ----------------------------- State -----------------------------

class AgentState(TypedDict, total=False):
    program_id: str

    # Stage 0
    metadata: dict

    # Stage 1
    raw_evidence: list[dict]
    classified_evidence: list[dict]

    # Stage 2
    extracted_skills: list[dict]
    skill_clusters: list[dict]

    # Stage 3
    plos: list[dict]

    current_stage: str
    checkpoint_status: Literal["pending", "approved", "needs_revision"]
    designer_notes: str


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


async def stage_3_plo_synthesis(state: AgentState) -> AgentState:
    from curriculum_agent.stages.plo_synthesis import run  # noqa: PLC0415
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


def review_skill_clusters(state: AgentState) -> AgentState:
    payload = interrupt("Stage 2 complete — review/edit skill clusters before PLO synthesis")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


def review_plos(state: AgentState) -> AgentState:
    payload = interrupt("Stage 3 complete — review/edit PLOs before PLO report")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


def review_plo_report(state: AgentState) -> AgentState:
    payload = interrupt("Stage 5 complete — review/edit PLO generic-specific classification")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


# --------------------------- Build graph -------------------------

def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("intake", stage_0_intake)
    g.add_node("stakeholder_needs", stage_1_stakeholder_needs)
    g.add_node("review_evidence", review_stakeholder_needs)
    g.add_node("skill_extraction", stage_2_skill_extraction)
    g.add_node("review_clusters", review_skill_clusters)
    g.add_node("plo_synthesis", stage_3_plo_synthesis)
    g.add_node("review_plos_node", review_plos)
    g.add_node("plo_report", stage_5_plo_report)
    g.add_node("review_plo_report", review_plo_report)

    g.set_entry_point("intake")
    g.add_edge("intake", "stakeholder_needs")
    g.add_edge("stakeholder_needs", "review_evidence")
    g.add_edge("review_evidence", "skill_extraction")
    g.add_edge("skill_extraction", "review_clusters")
    g.add_edge("review_clusters", "plo_synthesis")
    g.add_edge("plo_synthesis", "review_plos_node")
    g.add_edge("review_plos_node", "plo_report")
    g.add_edge("plo_report", "review_plo_report")
    g.add_edge("review_plo_report", END)

    return g.compile(checkpointer=checkpointer)
