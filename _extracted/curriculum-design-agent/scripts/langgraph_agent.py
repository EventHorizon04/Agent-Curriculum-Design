"""
Curriculum Design Agent — LangGraph state machine skeleton.

This is a starting scaffold. Each stage's actual logic lives in
src/curriculum_agent/stages/<stage_name>.py — this file just wires them
together into a graph with human-in-the-loop checkpoints.

Usage:
    from langgraph.checkpoint.sqlite import SqliteSaver
    from curriculum_agent.graph import build_graph

    saver = SqliteSaver.from_conn_string("checkpoints.db")
    graph = build_graph(checkpointer=saver)

    # Start a new run
    config = {"configurable": {"thread_id": "program-cs-2025"}}
    result = graph.invoke({"program_id": "cs-2025"}, config)

    # When graph hits an interrupt, the UI fetches the state, lets the
    # designer review, then resumes with edits via:
    graph.update_state(config, edited_state)
    graph.invoke(None, config)  # resume
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt


# ----------------------------- State -----------------------------

class AgentState(TypedDict, total=False):
    """Shared state across all stages. Each stage reads what it needs
    and writes its output back."""
    program_id: str

    # Stage 0
    metadata: dict  # serialized ProgramMetadata

    # Stage 1
    raw_evidence: list[dict]
    classified_evidence: list[dict]

    # Stage 2
    extracted_skills: list[dict]
    skill_clusters: list[dict]

    # Stage 3
    plos: list[dict]

    # Stage 4
    ylo_matrix: dict

    # Cross-cutting
    current_stage: str
    checkpoint_status: Literal["pending", "approved", "needs_revision"]
    designer_notes: str


# --------------------------- Stage nodes -------------------------
# Each is a placeholder — implement in stages/<stage>.py and import here.

def stage_0_intake(state: AgentState) -> AgentState:
    """Validate and store ProgramMetadata. Synchronous, no LLM."""
    # TODO: implement in stages/intake.py
    # - Load metadata from state['metadata'] (already collected by UI form)
    # - Validate via ProgramMetadata Pydantic model
    # - Persist to Postgres
    state["current_stage"] = "intake"
    return state


def stage_1_stakeholder_needs(state: AgentState) -> AgentState:
    """Collect and classify stakeholder evidence."""
    # TODO: implement in stages/stakeholder_needs.py
    # - Read evidence (uploaded files / scraped data) from MinIO/DB
    # - For each evidence item, run classification prompt (need/requirement/want)
    # - Store as StakeholderEvidence in Postgres
    # - Embed evidence into Qdrant for retrieval
    state["current_stage"] = "stakeholder_needs"
    return state


def stage_2_skill_extraction(state: AgentState) -> AgentState:
    """Extract skills, cluster them, score demand."""
    # TODO: implement in stages/skill_extraction.py
    # 1. LLM extraction per evidence → ExtractedSkill list
    # 2. KeyBERT extraction as backup signal
    # 3. Embed skill names with BGE-M3
    # 4. HDBSCAN/KMeans cluster on embeddings
    # 5. LLM names each cluster → SkillCluster
    # 6. Compute demand_score (frequency × recency × stakeholder_breadth)
    state["current_stage"] = "skill_extraction"
    return state


def stage_3_plo_synthesis(state: AgentState) -> AgentState:
    """Synthesize 4-6 PLOs from approved skill clusters."""
    # TODO: implement in stages/plo_synthesis.py
    # 1. Filter clusters: keep only is_common_need=True or top demand_score
    # 2. Run Stage 3 prompt with full context (HEAVY model)
    # 3. Validate each PLO with SMART validator (LIGHT model)
    # 4. If any PLO fails validation, regenerate that one specifically
    # 5. Save to Postgres with version=1
    state["current_stage"] = "plo_synthesis"
    return state


def stage_4_ylo_derivation(state: AgentState) -> AgentState:
    """Derive YLO matrix from approved PLOs."""
    # TODO: implement in stages/ylo_derivation.py
    # 1. For each approved PLO, run Stage 4 prompt → list[YLO]
    # 2. Build YLOMatrix
    # 3. Run validate_coverage() — if any issues, regenerate problematic YLOs
    # 4. Save matrix to Postgres
    state["current_stage"] = "ylo_derivation"
    return state


# -------------------- Human-in-the-loop nodes --------------------

def review_stakeholder_needs(state: AgentState) -> AgentState:
    """Pause for designer to review classified evidence."""
    interrupt("Stage 1 complete — review classified evidence before clustering")
    return state


def review_skill_clusters(state: AgentState) -> AgentState:
    """Pause for designer to review/edit skill clusters."""
    interrupt("Stage 2 complete — review/edit skill clusters before PLO synthesis")
    return state


def review_plos(state: AgentState) -> AgentState:
    """Pause for designer to review/edit generated PLOs."""
    interrupt("Stage 3 complete — review/edit PLOs before YLO derivation")
    return state


def review_ylo_matrix(state: AgentState) -> AgentState:
    """Final review of full YLO matrix."""
    interrupt("Stage 4 complete — final review of PLO/YLO matrix")
    return state


# --------------------------- Build graph -------------------------

def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    # Stages
    g.add_node("intake", stage_0_intake)
    g.add_node("stakeholder_needs", stage_1_stakeholder_needs)
    g.add_node("review_evidence", review_stakeholder_needs)
    g.add_node("skill_extraction", stage_2_skill_extraction)
    g.add_node("review_clusters", review_skill_clusters)
    g.add_node("plo_synthesis", stage_3_plo_synthesis)
    g.add_node("review_plos_node", review_plos)
    g.add_node("ylo_derivation", stage_4_ylo_derivation)
    g.add_node("review_ylo", review_ylo_matrix)

    # Linear flow with HITL between stages
    g.set_entry_point("intake")
    g.add_edge("intake", "stakeholder_needs")
    g.add_edge("stakeholder_needs", "review_evidence")
    g.add_edge("review_evidence", "skill_extraction")
    g.add_edge("skill_extraction", "review_clusters")
    g.add_edge("review_clusters", "plo_synthesis")
    g.add_edge("plo_synthesis", "review_plos_node")
    g.add_edge("review_plos_node", "ylo_derivation")
    g.add_edge("ylo_derivation", "review_ylo")
    g.add_edge("review_ylo", END)

    return g.compile(checkpointer=checkpointer)
