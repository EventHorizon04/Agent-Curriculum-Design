# Single-agent mode (design)

Date: 2026-11-13. Branch: `feat/four-agent-pipeline`. Status: awaiting the designer's approval.

## Why

Research Plan phase 1 compares two ways of producing PLOs from the same evidence: the existing pipeline of chained agents ("multi") and one agent doing the whole job ("single"). Multi exists; single does not, and it blocks the phase-1 lock runs (three passing runs for each mode), the HITL button test and the three-model comparison.

The designer's definition: **single is one LLM whose whole behaviour is set by one prompt, with the same tools the multi-agent pipeline has.** It also has to be usable from the web UI as a real way to design a program, not only from a research script.

## What is compared, and what is held equal

The one variable is the structure of the work.

| | multi | single |
|---|---|---|
| LLM calls | many stage calls, each with its own prompt and role | one tool loop, one system prompt |
| Context | each call sees its slice | one context sees everything it has read |
| Checking | separate judges, majority vote, repair instructed by code, review loop with send-back | the agent checks its own work; **no vote, no separate judge, no send-back loop** |

Held equal (decided by the designer unless marked *builder's call*):

- Model, provider and temperature (0). Same evidence as input.
- The tool set (below), handed over as one bag.
- The pure-code SMART hard check is the last word on every PLO.
- Two human checkpoints: Needs, then PLOs.
- What is stored: Needs and PLOs in the existing tables, each tracing to evidence. `demand_score` and stakeholder types are stored on single's Needs and computed by code, as in multi.
- Domain rules that are code in multi stay code in single: evidence class from `StakeholderType`, the 6-10 core PLO band, non-empty evidence trail, forbidden words, one declared verb.

## Goals

1. A program can be created (or copied) in single mode and taken from evidence to an approved PLO report in the web UI.
2. Single starts from the stored evidence and produces Needs itself. It does not reuse multi's skills or Needs.
3. Single stores **Needs and PLOs with the evidence they cite, and no skills.**
4. Token usage and wall time of a single run are recorded so they can be set against a multi run on a copy of the same evidence.

## Non-goals

- The side-by-side "arena" page. The designer wants it (two copies next to each other with tokens, time, PLO counts) but after phase 1 is finished. Separate spec.
- Storing extracted skills or skill groups for single. Extraction quality is therefore not comparable between modes; Needs and PLOs are.
- Voting, a separate SMART judge, the review loop, send-back, `plo_feedback_actions` for single.
- Switching a program's mode after creation.
- LLM response cache for single. Every single run calls the model.

## Anti-goals

- A single mode that quietly reuses multi's stage prompts or chains several role-specific calls. That would be multi under another name and the comparison would mean nothing.
- A single mode whose PLOs skip the code hard check, or that can declare a hard failure passed.
- Any change to what a multi run does or stores.

## Decisions that relax a project rule

These are the designer's, given in conversation on 2026-11-13, and should be added to `CLAUDE.md` when this is built.

- **Rule 5 (SMART gate).** In single mode the soft criteria are the agent's own judgement, one run, no vote. The hard floor is unchanged.
- **Rule 7 (PLO tail).** Single has no `plo_review` job and no send-back. The PLO checkpoint is still the designer approving the stored set before the report.
- **Pitfall "don't pass full evidence text into synthesis prompts".** Single reads evidence text in its own context; that is what the mode is.
- **Pitfall "never cluster across a KSEC bucket".** Single does no clustering. A Need it writes may carry more than one KSEC tag.

## Mode is a property of the program

- New program field `agent_mode: "multi" | "single"`, default `"multi"`, stored on the program row (Alembic migration; existing rows become `multi`).
- Chosen on the intake form at creation. `POST /programs/{id}/copy` accepts an optional `agent_mode`; omitted, the copy keeps the source's mode. A copy that changes mode must be `evidence_only`; a `full` copy with a different mode is refused, because the two modes' Needs are different shapes.
- Not editable afterwards.
- A comparison is two `evidence_only` copies of one program, one per mode.

*Builder's call:* field name, and how the programs list shows the mode.

## The run

Two jobs, one per half, each ending at a checkpoint. The existing routes dispatch on the program's mode so the UI buttons stay where they are:

- `POST /needs/run` on a single program starts job kind `single_needs`.
- `POST /plos/run` on a single program starts job kind `single_plos`. Nothing is chained after it.

Both halves use the **same system prompt** (`prompts/single_agent.py`, one builder). The first user message says which half is being run and carries that half's input. *Builder's call (agreed in conversation):* the second half starts a fresh context from the approved Needs rather than holding the first conversation open while a human reviews.

The loop follows the existing agent loops (`smart_agent.py`, `plo_review_agent.py`): Instructor, a Pydantic step with `reasoning_th` and a discriminated action, tool results fed back as user messages, a repeated identical call refused (*added during the build, 2026-11-14:* except a call whose answer depends on stored state, namely `list_sibling_plos`, `get_need` and `need_detail`, which may be repeated after the agent has saved, dropped or finished something, so it can re-read its own work), malformed steps tolerated a bounded number of times, a closing call that only allows finishing when the turn budget runs out.

### One slot

New slot `single_agent` in `SLOTS`, not disableable. It resolves like every other slot, so `PIPELINE_PROVIDER` / `PIPELINE_MODEL` put it on the same model as multi; its `default_models` match the `plo_synthesis` slot's. Usage is recorded under this slot name, which is how a run's cost is read (`GET /programs/{id}/usage`).

### Tools

The same seven names multi's agents have, in one bag, available in both halves:

| tool | in single |
|---|---|
| `get_evidence(evidence_id, part)` | returns one part of an evidence item's text. Unlike multi's version it is not limited to cited evidence, has no 3-read cap, and pages through the whole text (multi's 600-char excerpt cannot support extraction) |
| `get_need(need_id)` / `need_detail(need_id)` | a Need drafted in this run (first half) or an approved Need (second half) |
| `list_sibling_plos()` | PLOs saved so far in this run |
| `check_hard(statement_th, action_verb_th)` | the pure-code hard check |
| `bloom_lookup(verb_th)`, `check_verbs(...)` | unchanged |

The opening message of the first half lists every evidence item (id, stakeholder type, source name, class `requirement`/`general`, length, number of parts) so the agent knows what there is to read. Evidence text itself arrives only through `get_evidence`.

*Builder's call:* part size (default 6000 characters, a setting), whether one `get_evidence` call may name several items, and whether `get_need` and `need_detail` share an implementation.

**Corpus size this is designed for.** The phase-1 test program has 14 evidence items, 9,537 characters in total, the longest 978 (measured on the copy DB, 2026-11-13). Every item fits in one part, so a first half is roughly 14 reads, about ten saves and a finish. At that size the whole history stays in context and nothing below applies.

**When the evidence does not fit the context** (designer's decision, 2026-11-14: handle it, do not refuse the run). The agent keeps its own notes and code drops the raw text:

- After reading an evidence item the agent must hand in a `Note` action: `evidence_id` and the points it found there, in its own words. This is an output action of the same loop, not another LLM call, and it is required on every run, large corpus or small, so the prompt and the behaviour are the same in both.
- Code tracks the prompt tokens each turn actually used. When they pass `single_agent_context_budget_ratio` (default 0.7) of the model's context window, code replaces the oldest raw `get_evidence` results in the history with a short marker pointing at the agent's note for that item, oldest first, until the history is back under budget. Only evidence text is dropped; notes, saved Needs and the agent's own steps stay.
- The agent may call `get_evidence` again on a dropped item. The repeated-call refusal does not apply to an item whose text was dropped.
- The trail is unaffected: notes carry the `evidence_id`, and `SaveNeed` still checks every cited id against the program.
- If the history cannot be brought under the window even with all evidence text dropped, the half ends with `stop_reason = context_full` and stores what was saved, by the partial-result rule below.
- The job result records how many evidence items had their text dropped, so a run that worked from full text can be told from one that worked from notes. Coarser Needs on a large corpus are a real property of the single structure and should show in the results, not be hidden.

No separate summarising call and no switch to a larger-context model: the first would be multi under another name, the second changes the model, which is held equal.

*Builder's call:* how the context window of the slot's model is known (a setting `single_agent_context_window_tokens` is enough; it need not be discovered), the marker text, and the note's length limit.

Besides tools, the step's action can be one of the output actions below. These are how the agent hands in work, not tools.

### First half: evidence → Needs (`single_needs`)

Output action `SaveNeed`: `statement_th`, `rationale_th`, `ksec_categories` (one or more), `bloom_level`, `source_evidence_ids` (at least one). Saving again with the id it was given replaces the draft; `DropNeed(need_id)` removes one. `Finish` ends the half.

Code, at each `SaveNeed`:
- every evidence id must belong to the program, otherwise the save is refused with the reason and the agent can retry;
- the Need gets its id.

Code, at `Finish` (one transaction, replacing the program's Needs as multi's stage does):
- `source_stakeholder_types` and `stakeholder_coverage` from the cited evidence;
- `demand_score` via the existing `compute_demand_score`. The corpus (the denominator) is the evidence cited by at least one Need of this run, the analogue of multi's "evidence that yielded a skill";
- `freq` = number of cited evidence items;
- `is_optional` via the existing `is_optional_group` rule with code-derived classes: a Need citing any `requirement` evidence is `requirement`; otherwise `need` when it cites more than one item and `want` when it cites one. `classification_coverage` records that one class. The LLM does not classify;
- evidence items the agent never opened, and evidence no Need cites, are logged and returned in the job result so the Need page can show them;
- fewer than 6 non-optional Needs logs the same policy warning multi logs. No cap on the number of Needs.

A run that ends (finish, turn cap or timeout) with at least one saved Need stores what it has and succeeds, with the stop reason in the job result. With none, the job fails and nothing is replaced. The job result carries `stop_reason` (`finished` | `turn_cap` | `timeout` | `context_full` | `malformed`), turns used, the number of evidence items whose text was dropped, and the unread and uncited evidence ids. *Builder's call:* for the research lock runs, only `finished` with no unread evidence counts as a pass; a capped run is usable in the UI but is not a passing run. *Added during the build, 2026-11-14.* `malformed` (the loop ended through its closing call after repeated malformed steps) is a fifth stop reason and is not a pass either: with the four values alone an unfinished run would have looked finished. *Added during the build, 2026-11-14.* An evidence item counts as read only when **every part** of it was fetched with `get_evidence`; a partly read item is listed in `unread_evidence_ids`, so a lock run cannot pass without reading long documents. The job result also lists `unnoted_evidence_ids` (opened, no Note handed in).

*Designer's decision of 2026-11-14, after the first real run.* `requirement` evidence (the institution's direction, the professional council) must be cited: every graduate capability such an item names has to be behind at least one Need, either added to the Need that asks for the same capability or written as a new Need. The first run read all three `institutional_direction` items as background, cited none, and so wrote no `requirement` Need; multi reaches those items through skill extraction. The prompt states the rule, and code refuses the **first** `Finish` of the needs half that leaves a requirement item uncited (`NeedsHandler.finish_refusal`), listing the items. A second `Finish` is accepted, because an item may name no graduate capability at all (pure institutional goals), and the prompt asks for the reason in `summary_th`; a finish on the last turn is never refused. Whatever stays uncited is in the job result as `uncited_requirement_evidence_ids`. This moves single toward multi's behaviour on purpose, as a design choice for the comparison.

*Designer's decision of 2026-11-14, after the cache-off lock runs* (`.scratch/reports/2026-11-14-cache-off-lock-runs.md`): the needs half must not finish with fewer than 6 core Needs without being asked once. Two of three single runs wrote Needs that each cited a single evidence item, which code marks optional, leaving 3 and 2 core Needs. Code refuses the **first** `Finish` when fewer than `MIN_NEEDS` (6) core Needs exist, listing the Needs that cite one item and the evidence no Need cites, and asks the agent to re-check which other items ask for the same capability. It is not a quota: citing an item that did not ask for the capability stays forbidden, and a second `Finish` is accepted. Each gate speaks once; when both hold at the same `Finish` they share one refusal. This is one more code-side nudge on the single agent and belongs in any single-vs-multi write-up.

`demand_score` is used to rank Needs inside one run. Its denominator differs slightly from multi's by construction, so scores are not compared across modes. *Builder's call.*

Re-running either half on a program that already has later-stage rows (PLOs, superseded PLOs, a stored report) follows whatever the multi routes do today for the same re-run; single adds no new rule there.

**Audit is part of the work.** Before sizing the Need change, the plan must list every reader of `member_skill_ids`, `top_skill_ids`, the skill counts and ratios, and any place that assumes one KSEC tag per unmerged Need (synthesis input, `plo_report`, the Need page and trace view, merge/split, scope guard), and say for each whether it already tolerates a skill-less, possibly multi-tag Need.

### The Need model without skills

`Need.member_skill_ids` currently requires at least one id. Single's Needs have none.

- Add `origin: "multi" | "single"` to `Need` (default `"multi"`, stored). `member_skill_ids` may be empty only when `origin == "single"`; multi's guarantee is untouched.
- For a single Need, `top_skill_ids` is empty, the skill counts are 0, and the ratio properties keep today's behaviour for an empty member list (1.0, no division). *Corrected 2026-11-14 after the code audit: returning 0 would mark the Need off-scope.*
- Scope guard: `is_in_scope` treats a single Need as in scope. Staying inside the program's field is the prompt's job in this mode; the designer can exclude a Need at the checkpoint. *Builder's call.*

### Need checkpoint

The `need_analysis` page and its actions work on single's Needs:

- approve; exclude / restore;
- **merge 2-5 Needs**: the merged Need's evidence, stakeholder types, `demand_score`, `freq` and class are recomputed by code from the union of evidence; KSEC tags are the sorted union. Today's designer merge has the model write the merged statement (the dialog supplies only a reason), so in single mode the single agent writes it: same system prompt, `single_agent` slot, a merge task as the first user message. *Corrected 2026-11-14 after the code audit.* Split works as today; *added during the build, 2026-11-14:* the merged statement is written by the single agent, as said here, and the dialog's reason is passed to it;
- the trace view shows evidence only (no skills section).

Evidence locks once Needs exist, as in multi.

### Second half: approved Needs → PLOs (`single_plos`)

Input chosen by code exactly as multi's synthesis chooses: active (not excluded, not merged-away) Needs, the 10 highest non-optional by `demand_score` as core, optional Needs outside the bound. The opening message lists them (id, statement, KSEC, Bloom, `demand_score`, stakeholder types, evidence ids) and names the Needs that lost the cut. The designer's `note_th` from the request is included.

Output action `SavePLO`: `statement_th`, `statement_en`, `action_verb_th`, `bloom_level`, `source_need_ids` (1-5), `rationale_th`, and the agent's own verdict on the seven soft SMART criteria with a short Thai reason for each it fails. `DropPLO`, `Finish` as above.

Code, at each `SavePLO`:
- Need ids must be in the input list, and a Need may be behind at most one PLO; a violation is refused with the reason;
- `hard_failures` runs on the statement and the result is returned to the agent, which may save again. This is the agent repairing its own work; there is no repair cap other than the turn budget.

Code, at `Finish` (one transaction, replacing the program's PLOs):
- `source_evidence_ids` = union of the cited Needs' evidence;
- `hard_failures` runs once more on every final statement and alone sets `smart_escalated`. An escalated PLO is stored and shown for human repair, never dropped;
- the agent's soft verdicts are stored in the existing `SMARTCheck` / `soft_flags` / findings shape, with `smart_validated_by = "single_agent"` (new allowed value) so the UI and any analysis can tell a self-judged verdict from a voted one;
- core count outside 6-10 logs the policy warning; more than 10 core PLOs cannot happen because the input is cut;
- core Needs from the input that no PLO cites are reported in the job result.

Same partial-result rule as the first half: at least one saved PLO stores and succeeds with a stop reason; none fails the job.

### PLO checkpoint and report

The designer approves the stored PLOs, then `plo_report` runs unchanged from what is stored. Manual PLO edits, revalidate and `POST /plos/from-needs` on a single program:

- hand edit and the hard check on save: unchanged;
- *Added during the build, 2026-11-14.* A revalidate of a hand-edited PLO keeps the stored `statement_th`, `statement_en`, `action_verb_th`, `bloom_level` and `rationale_th`, and every revalidate (edited or not) keeps the stored `distinctive_feature_th` (the agent judges the sentence and does not reword it, `keep_wording`; an agent-written rationale about a different sentence would be wrong beside the kept wording, the same as multi's revalidate). A redraft from `POST /plos/from-needs` has no distinctive feature, because `SavePLO` carries no such field;
- revalidate and the designer's merge-from-Needs redraft run through the `single_agent` slot, with no vote. The system prompt is the same one, unchanged; only the first user message differs (it names the one PLO or the Needs to draft from). The stored verdict is `smart_validated_by = "single_agent"`, hand-edited or not. It must not call the multi slots.

### Budgets

Settings, with defaults: `single_agent_max_turns` 80 per half, `single_agent_timeout_seconds` 1800 per half, `single_agent_evidence_part_chars` 6000, `single_agent_context_budget_ratio` 0.7, `single_agent_context_window_tokens` (set to the pinned model's window). The turn budget is per half and is the designed-for-small-corpus number; a large corpus needs it raised, and the turn cap, not a refusal at the start, is what stops a run that is too long. *Builder's call on the numbers after one real run;* the report of that run should state what the run actually used.

## UI

- Intake form: mode choice with a one-line Thai explanation of each. Programs list: copy offers the mode.
- Rail for a single program: intake → stakeholder needs → need analysis → PLO checkpoint → report. No skill-extraction stage. *Builder's call:* whether the PLO checkpoint reuses the `plo_synthesis` page or the `plo_review` page; it must show each PLO, its evidence trail, hard-check status and the agent's own soft verdicts labelled as self-judged, and must not show vote counts, review findings or the send-back trail.
- While a half runs, the page shows the job as running the way it does for multi.
- All new student-facing or designer-facing strings in Thai; existing visual identity.

## Sessions / graph

The job routes call stages directly; only `/sessions` drives the LangGraph graph. Single runs through the job routes only. Starting a graph session for a single program is refused with a clear message. `stage_reached` must give the right rail position for a single program from its stored rows.

## Testing

- Validators first: `Need` with `origin="single"` and no skills is valid; with `origin="multi"` and no skills still fails; PLO trail validators unchanged.
- Pure-code pieces: demand/class/optional derivation from cited evidence; save-time refusals; finish-time hard gate sets `smart_escalated`; a Need behind two PLOs refused.
- Context handling with a scripted fake LLM and a tiny window: oldest evidence text is dropped first and replaced by the marker, notes and saved Needs survive, a dropped item can be read again, `context_full` stores partial work, and a small corpus drops nothing.
- The loop with a scripted fake LLM: reads evidence in parts, notes, saves, finishes; turn cap and timeout store partial work with a stop reason; nothing saved fails the job and leaves stored rows alone.
- Routes: `/needs/run` and `/plos/run` dispatch by mode; a multi program's behaviour is byte-for-byte what it was; mode-changing `full` copy refused.
- `scripts/dump_prompts.py --check` passes with the new prompt in `docs/prompt-inventory.md`.
- One real run on the copy DB (`curriculum_phase1`, never the shared DB) from evidence to report, reported under `.scratch/reports/` with tokens, turns and wall time for each half.

## Left to the builder

File layout under `stages/` and `prompts/`, the exact step/action models, migration details, part size and budgets, the wording of the single system prompt (it must cover everything multi's stage prompts cover: KSEC, Bloom table use, forbidden words, one declared verb, SMART soft criteria, Need-writing rules, staying in the program's field, actor is the graduate), and the page reuse choice above.
