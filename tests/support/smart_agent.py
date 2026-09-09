"""Shared stand-ins for the SMART validation agent.

Two mock levels, and the choice between them matters:

**Level 1 — stub `run_smart_agent`.** The default for every stage, route,
persistence and contract test. `agent_verdict` builds one scripted result and
`scripted_agent` plays a sequence of them, recording the drafts and contexts it
was handed so a test can assert on the sibling list without asserting on turn
counts.

**Level 2 — script tool *intents* and run the real tools** (`FakeToolModel` in
`tests/unit/test_smart_agent.py`). Only for the loop's own tests.

What neither level does is script raw provider responses turn by turn. That
couples every test to the loop's internal turn structure — change one tool call
per turn to parallel tool calls and forty tests break at once. It is the same
coupling as the old `assert len(fix_calls) == 3`, which is what forced the retry
loop's tests to be rewritten rather than retargeted.
"""

from __future__ import annotations

from typing import Any

from curriculum_agent.models import SmartFinding
from curriculum_agent.smart_vocabulary import SmartFindingCode
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages.smart_agent import SmartAgentResult, ValidationReason


def agent_verdict(
    draft: Any,
    *,
    statement_th: str | None = None,
    action_verb_th: str | None = None,
    soft_findings: list[SmartFinding] | None = None,
    diagnosis_th: str | None = None,
    repair_count: int = 0,
    turns: int = 2,
    reason: ValidationReason = ValidationReason.FINISHED,
    ran: bool = True,
) -> SmartAgentResult:
    """One scripted verdict over a draft.

    Defaults to accepting the draft unchanged with every soft criterion passing
    — what a test uses when it only needs the validator out of the way.
    """
    return SmartAgentResult(
        statement_th=statement_th if statement_th is not None else draft.statement_th,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        action_verb_th=action_verb_th if action_verb_th is not None else draft.action_verb_th,
        rationale_th=draft.rationale_th,
        distinctive_feature_th=draft.distinctive_feature_th,
        source_need_ids=list(draft.source_need_ids),
        soft_findings=soft_findings or [],
        diagnosis_th=diagnosis_th,
        repair_count=repair_count,
        turns=turns,
        reason=reason,
        ran=ran,
    )


def soft_finding(code: SmartFindingCode, note_th: str = "ทดสอบ") -> SmartFinding:
    return SmartFinding(criterion=code, severity="soft", note_th=note_th)


class ScriptedAgent:
    """An async stub whose Nth call returns the Nth scripted verdict.

    The last verdict repeats. That matters because phase B validates N drafts
    concurrently: a test that only cares about PLO1 must not have to script ten
    verdicts to get there.
    """

    def __init__(self, *verdicts: Any) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[tuple[Any, Any]] = []

    async def __call__(
        self, draft: Any, ctx: Any, metadata: Any, *, need_statements_th: Any = ()
    ) -> SmartAgentResult:
        self.calls.append((draft, ctx))
        index = min(len(self.calls) - 1, len(self._verdicts) - 1)
        chosen = self._verdicts[index] if self._verdicts else None
        if chosen is None:
            return agent_verdict(draft)
        if callable(chosen):
            return chosen(draft)
        return chosen

    @property
    def contexts(self) -> list[Any]:
        return [ctx for _, ctx in self.calls]


def scripted_agent(*verdicts: Any) -> ScriptedAgent:
    """`scripted_agent()` accepts every draft cleanly; pass callables taking the
    draft to shape individual verdicts."""
    return ScriptedAgent(*verdicts)


def set_agent(monkeypatch: Any, *verdicts: Any) -> ScriptedAgent:
    """monkeypatch form, for tests that patch and then call `run()` at the same
    indent. Returns the stub so a test can read `.calls` / `.contexts`."""
    stub = scripted_agent(*verdicts)
    monkeypatch.setattr(ps, "run_smart_agent", stub)
    return stub


# --- names the pre-agent tests used, kept pointing at the new stub ---------
#
# Fifteen call sites only ever needed "the gate said fine". They keep working
# through these two, so replacing the soft judge with the agent was a one-line
# substitution per site rather than fifteen rewrites.


def set_soft_judge(monkeypatch: Any, judge: Any | None = None) -> ScriptedAgent:
    return set_agent(monkeypatch)


def patch_soft_judge(judge: Any | None = None) -> Any:
    from unittest.mock import patch

    return patch.object(ps, "run_smart_agent", scripted_agent())


def soft_judge_ok() -> Any:
    """A verdict with every soft criterion true, shaped from the draft it sees."""
    return agent_verdict
