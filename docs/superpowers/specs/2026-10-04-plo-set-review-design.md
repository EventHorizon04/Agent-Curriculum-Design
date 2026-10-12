# Review the PLO set before the report — design

> Partly superseded by 2026-10-12-plo-qa-agent-design.md (placement, the single call, the 503, the rule 7 text).

**Date:** 2026-10-04
**Amends:** immutable rule 7 in `CLAUDE.md` (a second pair of stages that share one checkpoint).

## The problem

Every check the pipeline runs on a PLO is about that PLO alone. The SMART gate
reads one statement against its own Needs; the duplicate check in
`plo_synthesis` reads Need *sentences* before anything is drafted. Nothing reads
the finished set as a set, and three kinds of problem only show up there:

- **Contextual redundancy between drafted PLOs.** On the tourism program
  (`program-2`) PLO1 and PLO4 both open with "ดำเนินการบริการท่องเที่ยวเชิงคุณภาพ";
  on the translation program PLO2 (translate legal documents using AI) and PLO6
  (translate business texts using digital tools) overlap. The Need-level check
  cannot see this: the Needs differed, the drafts converged.
- **KSEC after folding.** A PLO's domain is the KSEC tag of the Needs behind it,
  one tag per Need, and folding never mixes tags. But a finished outcome often
  spans domains — "ปฏิบัติตนอย่างมีจริยธรรม… ในการแปลและล่ามหน้างาน" is E as much
  as S — and Thai curriculum mapping allows a PLO to sit under more than one.
- **Bloom across the set.** Each PLO's level is inherited from its Need's
  `group_bloom`; nothing asks whether the level suits the verb, the object and the
  degree, or whether the set as a whole leans on create for a bachelor's program.

Clustering is the upstream cause of some of this, and it does not hold still:
llama groups the same short Thai names differently run to run (see the
`build_cluster_skills_prompt` docstring, 2026-10-04 measurement). Rather than keep
tuning a stage that will not settle, this adds a reviewer that reads the output.

## Decisions (from the design conversation)

1. **Advisory only.** The reviewer reports what to improve and why. It changes
   no PLO, no KSEC tag, no Bloom level, no Need. The designer acts on it.
2. **KSEC may be several.** A suggested mapping is a set drawn from K, S, E, C.
3. **Placement:** `plo_synthesis → [checkpoint] → plo_review → plo_report → [checkpoint]`.
   The review and the report share the report's checkpoint.
4. **Stored, shown on the report page.** Not in the Excel export — that file goes
   to MHESI, and internal advice does not belong in it.
5. **One structured call over the whole set** (approach A). Not three calls, not a
   tool-using agent.

## Shape

```
POST /plos/report/run ─┐
graph: review_plos_node ┴─► plo_review.run(state)
                              ├─ fingerprint the current PLO set
                              ├─ stored review has the same fingerprint? → reuse, no call
                              ├─ else: one call on the plo_review slot
                              │     └─ accept_review  ← pure code, drops bad entries
                              ├─ store the review (one row per program)
                              └─ state["plo_review"] = review | None
                           ─► plo_report.run(state)   ← adds review + review_stale to the report
```

New files: `stages/plo_review.py`, `prompts/plo_review.py`, one migration. The
graph gets a `plo_review` node with no interrupt of its own, wired
`review_plos_node → plo_review → plo_report`. It is **not** a designer stage:
`DESIGNER_STAGES`, `REVIEW_NODE_STAGE` and `stage_reached` are unchanged, and the
Pipeline rail keeps five stages.

## The call

Slot `plo_review` in `config.SLOTS`, after `validation`:
`SlotSpec("plo_review", "plo_review_provider", "plo_review_model", default_models={"openrouter": "z-ai/glm-5.3-flash"}, disableable=True)`,
provider default `openrouter`. glm-5.3-flash because the task is judging and
labelling, it held up on the need_dedup probe and in the SMART agent, and it is
one call per program, so its reasoning latency is paid once. `disableable`
because the review is optional: `PLO_REVIEW_PROVIDER=` (empty) skips it and the
report says so. Wrapper `llm.complete_plo_review`. Timeout
`plo_review_timeout_seconds` (default 180) around the call; `max_tokens` 8192;
temperature 0.

**Input** (`build_plo_review_prompt`), Thai, one user turn:

- program line: `build_program_context_th(metadata)` (field + degree level);
- per PLO: `plo_id`, core or optional, `statement_th`, `action_verb_th`,
  `bloom_level`, current KSEC (computed in code from its Needs, `EC` written as
  `E|C`), and each source Need's `statement_th`.

**Rubric** (system prompt, Thai). Three questions plus a summary:

1. *Redundancy* — groups of 2-3 PLOs a curriculum committee would read as one
   outcome: same main task on the same kind of object, differing only in context,
   tool or wording. Sharing a field or a tool is not redundancy (every PLO of a
   translation program translates something). For each group: why, and a
   suggestion (merge, or sharpen one PLO's object so they part).
2. *KSEC* — which of K, S, E, C the outcome as written belongs to, one or more,
   judged from what the graduate does: K = knowing/explaining a body of knowledge,
   S = performing a professional task, E = ethical conduct, C = personal
   attributes (adaptability, leadership, self-development). One entry per PLO,
   with a reason.
3. *Bloom* — whether the declared level fits the verb, its object and the degree
   level; if not, the level it should be. Only PLOs with a concern get an entry.
   Plus one note on the set's distribution.
4. *Summary* — two to five sentences for the designer, most important first.

The rubric says outright that the reviewer changes nothing and must not rewrite
statements, and that a clean set is a valid answer (empty lists).

**Response schema** (instructor → pydantic, all lists default empty):

```python
class _Redundancy(BaseModel):    plo_ids: list[str]; reason_th: str; suggestion_th: str
class _KsecVerdict(BaseModel):   plo_id: str; suggested: list[str]; reason_th: str
class _BloomVerdict(BaseModel):  plo_id: str; suggested_level: str | None; reason_th: str
class _ReviewResponse(BaseModel):
    redundancies: list[_Redundancy]; ksec: list[_KsecVerdict]; bloom: list[_BloomVerdict]
    bloom_distribution_th: str = ""; summary_th: str = ""
```

Fields are deliberately loose (`str`, not `Literal`): a validator failure fails
the whole call and loses every good entry with the bad one — the lesson of
`supporting_indices` and `accept_groups`. Judging happens in code.

## `accept_review` — pure code

Turns `_ReviewResponse` plus the PLO set into the stored `PLOSetReview`. Entry by
entry, never all-or-nothing:

- **Redundancy:** keep known, distinct plo_ids; drop the group if fewer than 2
  remain or more than 3 were named (which member to cut is the model's judgement,
  as in `accept_groups`); drop an exact duplicate group; drop if `reason_th` is
  empty.
- **KSEC:** drop entries for unknown plo_ids and later duplicates of one plo_id;
  keep only values in {K, S, E, C} (upper-cased, `EC`/`E|C` expanded to E and C);
  drop the entry if none remain. `current` is filled **in code** from the PLO's
  Needs, and `agrees` is computed in code (`set(suggested) == current`, with EC
  read as {E, C}) — never taken from the model.
- **Bloom:** drop unknown plo_ids, duplicates, and a `suggested_level` that is not
  a `BloomLevel` value (the entry stays, level `None`); `declared` filled in code;
  drop an entry whose suggested level equals the declared one and whose reason is
  empty.
- Text fields are stripped; nothing is truncated.

Every drop is counted and logged in one line (`plo_review: kept r/k/b, dropped …`).

## Stored model

`models.PLOSetReview` (crosses the API boundary):

```python
class RedundancyFinding(BaseModel):  plo_ids: list[str]; reason_th: str; suggestion_th: str
class KsecFinding(BaseModel):        plo_id: str; current: list[str]; suggested: list[str]; agrees: bool; reason_th: str
class BloomFinding(BaseModel):       plo_id: str; declared: BloomLevel; suggested_level: BloomLevel | None; reason_th: str
class PLOSetReview(BaseModel):
    program_id: str; plo_fingerprint: str; model: str; created_at: datetime
    redundancies: list[RedundancyFinding]; ksec: list[KsecFinding]; bloom: list[BloomFinding]
    bloom_distribution_th: str; summary_th: str
```

Table `plo_reviews` (migration, `down_revision` = current head): `program_id`
primary key and FK to `programs`, `plo_fingerprint` text, `model` text,
`created_at` timestamp, `review` JSONB (the findings and texts). One row per
program; a new review replaces the old one. `PLOReviewRepository.get /
upsert / delete_by_program`, and the program delete cascade drops the row with
the program's other rows.

## Staleness

`plo_fingerprint(plos)` = sha256 over the PLOs sorted by `plo_id`, each
contributing `plo_id`, `statement_th`, `bloom_level`, `action_verb_th`,
`is_optional` and its sorted `source_need_ids`. Any edit, re-synthesis, merge or
revalidation that rewrote a statement changes it. A review is **stale** when its
fingerprint differs from the current set's. The report carries `review_stale`;
the API's GET answers it too. Stale reviews are shown, labelled — never silently
dropped and never presented as current.

`plo_review.run` reuses a stored review whose fingerprint matches instead of
calling the model, so opening or re-running the report on an unchanged set costs
nothing. `POST /plos/review/run` always calls.

## API

- `POST /programs/{id}/plos/report/run` — runs `plo_review.run`, then
  `plo_report.run`. `PLOReportResponse` gains `review: PLOSetReview | None` and
  `review_stale: bool`.
- `POST /programs/{id}/plos/review/run` — forces a fresh review; 422 if the
  program has no PLOs, 409 if a review for the program is already in flight
  (per-process single-flight, same pattern and same limit as
  `plo_synthesis._SYNTHESIS_IN_FLIGHT`), 503 with a Thai detail if the slot is
  disabled or the call failed (nothing stored).
- `GET /programs/{id}/plos/review` — `{ review: PLOSetReview | null, stale: bool }`.

The report page UI (rendering the four sections, the stale label, the re-run
button) belongs to the frontend session; this work delivers the API, the schema
and the field names above.

## Failure

The review never blocks the report. Slot disabled, provider error, timeout, a
truncated answer, or an answer `accept_review` empties entirely: log a warning,
store nothing, and hand `plo_report` whatever is stored (possibly stale, possibly
`None`). The report runs as it does today. No finding is manufactured for a review
that did not run — the same discipline as the SMART agent's `code_only`.

## Rule 7, amended

> **Human-in-the-loop at every stage boundary — except two shared checkpoints.**
> Stages never auto-chain into the next without checkpoint approval; the
> exceptions are skill_extraction → need_combination, which share a checkpoint
> after need_combination so the designer reviews raw skills and distilled Needs
> together, and plo_review → plo_report, which share the report's checkpoint so
> the designer reads the set review beside the report it is about.

## Testing

Unit (TDD, mutation-checked):
- prompt builder: every PLO, its Needs and current KSEC reach the prompt; the
  rubric names the three questions, multi-KSEC, "changes nothing", empty lists
  allowed;
- `accept_review`: each drop rule; `agrees` and `current` computed in code even
  when the model claims otherwise; EC expansion;
- fingerprint: stable under reordering, changes on each listed field;
- `plo_review.run`: reuse on matching fingerprint (no call); call and store on
  mismatch; every failure path stores nothing and returns the stored review;
  disabled slot never calls;
- repository round-trip and cascade; graph wiring (`plo_review` between
  `review_plos_node` and `plo_report`, no interrupt, not in `DESIGNER_STAGES`);
  routes (report includes review fields; review/run 409/422/503; GET).
- config: the new slot walks `Settings.model_fields` like the others
  (`test_llm_slots.py`), and `""` disables it.

**Live measurement before calling it done** (tourism program now; translation
program after its PLOs are re-synthesised), 3 runs each, glm-5.3-flash:

- must flag tourism PLO1 + PLO4 as redundant in at least 2 of 3 runs;
- must suggest E (alone or with S) for the ethics/conduct PLOs ("ปฏิบัติงาน…ด้วย
  ความยึดมั่นในคุณธรรมจริยธรรม", "ปฏิบัติตนอย่างมีจริยธรรม…");
- must not invent plo_ids (`accept_review` drop count for unknown ids = 0 in
  most runs);
- one call stays under the 180 s timeout.

Record the results in this spec under "Measured" before merging.

## Out of scope

- Acting on the review (auto-merge, re-tagging KSEC, changing Bloom). Advisory only.
- A PLO-level KSEC field. The reviewer suggests; storage of an accepted mapping is
  a separate decision.
- The Excel export and the frontend rendering.
- Reviewing Needs or clustering output.

## Measured (2026-10-05)

Tourism program (`program-2`, 9 PLOs), `_call` invoked directly, nothing stored, 3 runs per variant:

| Variant | Answered | Time per run | PLO1+PLO4 redundant | KSEC entries | Unknown ids dropped |
|---|---|---|---|---|---|
| glm-5.3-flash, reasoning unbounded | 0/3 | 175 s (truncated at 8192 tokens), 180 s, 180 s (timeouts) | – | – | – |
| glm-5.3-flash, `reasoning_max_tokens=1024` | 3/3 | 48 s, 45 s, 57 s | 3/3 (as PLO1+PLO4+PLO9) | 9/9 every run | 0 |
| llama-3.3-70b | 3/3 | 22 s, 23 s, 39 s | 3/3 (as PLO1+PLO4+PLO9) | 4, 2, 2 of 9 | 0 |

- glm bounded met every criterion: the "ดำเนินการบริการท่องเที่ยวเชิงคุณภาพ" trio flagged every run; the ethics PLO6 kept E|C every run; PLO8 (current E|C from its Need, statement about planning a project) suggested S+E every run — a useful catch the code-derived KSEC cannot make; Bloom notes were specific (PLO8 "ประเมินผลกระทบ…อย่างเป็นระบบ" → evaluate).
- llama skipped most KSEC entries despite the rubric requiring one per PLO, and its Bloom reasons did not follow from the statements (e.g. "ออกแบบและพัฒนา" → evaluate).
- Decision: glm-5.3-flash with hidden reasoning bounded at 1024 tokens (`plo_review._MAX_REASONING_TOKENS`). On this endpoint a bound may switch reasoning off (see CLAUDE.md on the validation agent); the bounded answers above are what was judged.
- Not yet measured: the translation program — its PLOs must be re-synthesised first (PLO1-PLO7 were lost to the pre-fix primary-key bug).
