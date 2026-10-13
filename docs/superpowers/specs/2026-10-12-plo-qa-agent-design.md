# PLO QA agent: the set review becomes the closing stage

Date: 2026-10-12. Status: design approved in chat section by section; spec under review.

Supersedes parts of `2026-10-04-plo-set-review-design.md`: decision 3 (placement),
decision 5 (one structured call, "not a tool-using agent"), the graph shape, the
`POST /plos/review/run` 503 on a disabled slot, and the "Rule 7, amended" text.
Its rubric, its loose response schema and `accept_review`'s entry-by-entry
judging stay, extended below.

## Why

The set review exists (`stages/plo_review.py`) but it is not what the designer
needs:

1. It is one LLM call, not an agent: it cannot check a suspicion before it
   reports it, and the set-level facts it reports (KSEC spread, Bloom
   distribution) are the model's prose rather than counts.
2. It is hidden inside "สร้างรายงาน" (`POST /plos/report/run` runs it first) and
   has no step, page or button of its own.
3. No page renders it.

The designer wants a **QA agent that reads the finished PLO set as a whole, as the
closing step** — not something folded into generating the PLOs or the report.

**Success:** after the PLOs are approved, the designer opens stage 06 "ตรวจคุณภาพชุด
PLO", runs the QA agent (or the pipeline runs it), and reads advice on six
questions, with every number on the page computed in code and every judgement
labelled as the agent's. The rail can show all six stages ●.

## Decisions (from the design conversation)

1. **Advisory only.** The agent reports what to improve and why; it changes no
   PLO, Need, KSEC tag or Bloom level. The designer acts through the pages that
   already exist (edit, merge on the PLO synthesis page).
2. **Its own stage, 06**, after the report, with its own page and run button.
   "สร้างรายงาน" stops running the review.
3. **Six questions:** redundancy, KSEC per PLO, Bloom per PLO (existing), plus
   KSEC coverage of the whole set, the Bloom distribution against the degree
   level, and important Needs that did not become a PLO.
4. **Hybrid agent (approach C):** code builds a dossier of the facts every review
   needs; the agent gets a small tool budget to check what it suspects.
5. **Little data, on purpose — information bias.** The more upstream detail the
   agent reads, the more it anchors on evidence wording or re-litigates earlier
   stages instead of judging the set as written, the way a curriculum committee
   reads it. It sees the set, the Need sentences behind it, and code-computed
   facts — no evidence text.
6. **Immutable rule 7 is waived for report → QA** by the designer's decision:
   after the PLO checkpoint, the report and the QA agent run straight through to
   the end of the session with no checkpoint between or after them.

## 1. Pipeline and graph

```
plo_synthesis → [review_plos_node: checkpoint 04] → plo_report → plo_review (QA agent) → END
```

- The `review_plo_report` node is removed. Its interrupt was the last approval;
  the session now ends `completed` after the QA agent.
- Why the waiver is safe to state in the rule: neither stage changes the
  designer's content. `plo_report` re-persists the PLO set the designer approved
  at checkpoint 04; the QA agent writes only its own `plo_reviews` row. A
  checkpoint between or after them gates nothing.
- `REVIEW_NODE_STAGE` drops `review_plo_report`. Graph sessions stored on
  2026-10-12: zero, so no thread is suspended on the removed node.
- `DESIGNER_STAGES` gains `plo_review` (sixth). Every existing name stays: the
  slot `PLO_REVIEW_*`, the `plo_reviews` table, the job kind `plo_review`, the
  routes under `/plos/review`.
- `stage_reached` gains `has_current_review`: a stored review whose fingerprint
  matches the program's current set → `plo_review`. A stale review does not
  count, so the rail falls back to `plo_synthesis` (05 ◐: the next thing to do).
  `ProgramRepository.list_all` computes it from the stored reviews, PLOs and Needs.
- A QA failure never fails the session (section 3): the review is advisory.

## 2. What the agent sees

### Dossier (code-built, one user turn at the start)

- Program line: `build_program_context_th(metadata)` (field + degree level).
- Per PLO, in stored order: `plo_id`, core/optional, `statement_th`,
  `action_verb_th`, `bloom_level`, current KSEC (from its Needs, EC as E|C), and
  each cited Need's `statement_th`.
- Set facts, computed in code (section 3 stores them):
  - `ksec_coverage`: PLO count per K/S/E/C (a PLO counts once in every domain its
    current KSEC holds), the missing domains, flags `all_k` and `no_e_or_c`;
  - `bloom_histogram`: PLO count per level, the degree level, flag
    `below_apply_majority` (more than half the PLOs below Apply);
  - core count against the 6-10 band.
  The flags are only rules with a source in the skill's `obe-principles.md`
  (a set entirely in K fails AUN-QA; a set that never reaches E/C skips what
  มคอ. requires; bachelor-level PLOs sit mostly at Apply and above). There is no
  numeric ceiling on Create: no source gives one, so that is the agent's
  judgement, written in `bloom_distribution_th`.
- Unused Needs, selected in code: Needs not cited by any PLO
  (`cited_need_ids`), the 5 with the highest `demand_score` plus every one whose
  `source_stakeholder_types` contains `professional_council`, de-duplicated,
  ordered by demand. Per Need: `need_id`, `statement_th`, `demand_score`,
  `ksec_category`, `source_stakeholder_types` (type names only), and why it is
  unused: `out_of_scope` (`not is_in_scope`), `unwritten` (`is_unwritten_need`),
  otherwise `lost_on_demand`.

### Deliberately absent (the information-bias rule)

| Not given | Why |
|---|---|
| Evidence text, in the dossier or through any tool | Upstream's job; the SMART agent already judges each PLO against its Needs (R). |
| Member skill names | Invites re-judging the clustering. |
| Shared-evidence share between PLOs | Measured misleading: an unrelated pair shared 55% of its evidence, a true duplicate pair under 20%. |
| SMART diagnoses / findings, and the previous review | Anchoring: the agent would restate an old verdict. |

A unit test pins this list against the built dossier.

### Tools (at most 4 calls per run)

1. `bloom_lookup(verb_th)` — the Thai Bloom table entry (`bloom_verbs`).
2. `check_verbs(plo_id)` — code facts on one PLO's verbs: does the statement open
   with the declared verb, how many verbs the declared phrase holds, which levels
   they can take (`smart_rules` / `bloom_verbs`).
3. `need_detail(need_id)` — for a Need **in the dossier's unused list only**:
   `rationale_th` (labelled as the model's explanation), member count, and the
   `stakeholder_coverage` counts behind its demand. No evidence text.

A fifth call is refused with an observation telling the agent to finish. The
agency is in choosing which suspicion to check, not in seeing more.

### Loop

The structured action loop `smart_agent` uses (instructor `Mode.JSON`, one step
object with a discriminated action: `CallTool` or `Finish`), not native
tool-calling, for the reasons in `smart_agent`'s docstring. At most 6 steps;
the 6th must be `Finish` or the run ends `code_only` (`failed`). Each step bounds
hidden reasoning at `_MAX_REASONING_TOKENS` (1024): unbounded, this slot answered
nothing 3/3 on the tourism set. A truncation with the bound in place is a
malformed step. Whole-run timeout `plo_review_timeout_seconds`, raised from 180
to 300.

`Finish` carries the loose fields of today's `ReviewAnswer` plus `coverage_th`
and `unused_needs: [{need_id, verdict, reason_th}]` with `verdict` a plain string
(`consider` / `ok_to_leave`, judged in code). It has no field for any number.

## 3. Stored data, staleness, failure

### `PLOSetReview` (JSONB in `plo_reviews.review`; no migration)

New fields all default, so the two stored rows still read:

| Field | Source | Content |
|---|---|---|
| `redundancies`, `ksec`, `bloom`, `summary_th`, `bloom_distribution_th` | agent, judged by `accept_review` | as today |
| `ksec_coverage` | code | `{counts: {K,S,E,C}, missing: [...], flags: [...]}` |
| `bloom_histogram` | code | `{counts: {level: n}, degree_level, flags: [...]}` |
| `coverage_th` | agent | its reading of the KSEC coverage |
| `unused_needs` | code selects, agent judges | per selected Need: the dossier facts above plus `verdict` (`consider` / `ok_to_leave` / `None` when the agent gave none) and `reason_th` |
| `reviewed_by` | code | `agent` or `code_only` |
| `code_only_reason` | code | `disabled` / `failed` / `timeout`, `None` for `agent` |
| `tool_calls` | code | `[{tool, arg}]` in call order, for the "what it looked at" list |

`accept_review` extends the existing entry-by-entry rules: an `unused_needs`
verdict for a Need not in the selected list is dropped; an unknown verdict string
becomes `None`; duplicates keep the first. Code-computed fields are never read
from the model.

### Staleness

`plo_fingerprint` hashes the PLO set as today **plus** the program's Needs as
sorted `(need_id, demand_score)` pairs, because the unused-Need answer depends on
them. The definition change makes both stored reviews stale once; they stay
shown, labelled.

### Failure

Slot disabled (`PLO_REVIEW_PROVIDER=`), timeout, a malformed or truncated step,
a step cap reached without `Finish`, or an answer `accept_review` empties
entirely: store the code-computed fields with `reviewed_by="code_only"` and the
reason, and no agent findings — none are manufactured, the `code_only`
discipline of the SMART agent. The job succeeds; it fails only on a database or
programming error. In the graph path the session completes either way.

## 4. API

- `POST /plos/report/run` stops running `plo_review`. `plo_report.run` no longer
  reads a review; `PLOReportResponse` and the report dict drop `review`,
  `review_stale` and `review_enabled`.
- `POST /plos/review/run` — job `plo_review`, always a fresh run. 422 with no
  PLOs. **No 503 for a disabled slot any more**: the job runs the code part and
  stores a `code_only` review. Result: `PLOReviewResponse`.
- `GET /plos/review` — `{review, stale, review_enabled}`, as today, with the new
  fields inside `review`.

## 5. Frontend

New page `frontend/src/pages/PloReview.tsx` at `/plo-review`, stage 06
"ตรวจคุณภาพชุด PLO", built by a subagent. Top to bottom:

1. Header ("ขั้นที่ 6", the title, a line saying the agent advises and changes
   nothing) and a run button ("ตรวจชุด PLO", or "ตรวจใหม่" once a review
   exists). While this program's `plo_review` job runs, `RunProgress` with
   `since` from the job.
2. Status line: reviewed by the agent (model, time — `created_at` is naive UTC,
   parse it as UTC), or by code alone with its reason; a stale notice ("ตรวจจาก
   PLO ชุดก่อน"); or never reviewed.
3. `summary_th`.
4. ภาพรวมทั้งชุด — the code facts first (KSEC counts with missing domains flagged,
   Bloom counts with the degree level and flag), then `coverage_th` and
   `bloom_distribution_th` beneath, labelled as the agent's reading.
5. ซ้ำซ้อน — groups with reason and suggestion; a link to the PLO synthesis page
   to merge.
6. KSEC รายข้อ — disagreements first, agreements collapsed; scrolls sideways on a
   phone rather than the page.
7. Bloom รายข้อ — declared → suggested, with the reason.
8. Need สำคัญที่ไม่ได้เป็น PLO — demand, KSEC, why unused, the agent's verdict
   and reason; a "ควรพิจารณา" Need links to the PLO synthesis page.
9. "agent ไปดูอะไรมาบ้าง" — `tool_calls`, collapsed.

Also: `constants/stages.ts` gains stage 06 (the rail and the program list follow);
`JOB_PAGE.plo_review` points at the new page; `PloReport.tsx` drops `plo_review`
from `PAGE_KINDS` and its "อนุมัติและปิด session" footer becomes a link "ไปตรวจ
คุณภาพชุด PLO →"; `Pipeline.tsx` drops the `plo_report` checkpoint text and the
`plo_synthesis` one reads "…ตรวจและแก้ PLO ก่อนสร้างรายงานและตรวจคุณภาพ"; the mock
layer answers `GET`/`POST` review with a sample covering every section. Only
`index.css` component classes, no Tailwind palette. The review panel designed for
the report page on 2026-10-10 is dropped; this page replaces it.

## 6. Tests

Backend (pytest, mocked sessions and a fake model, as the SMART agent tests do):

- Code facts: KSEC counts with EC expanded to E and C; `all_k`, `no_e_or_c`;
  Bloom histogram and `below_apply_majority`; unused-Need selection (top 5 by
  demand plus council-backed, de-duplicated, ordered; the three exclusion
  reasons).
- Information bias: the built dossier contains no evidence text, no skill name,
  no SMART diagnosis and no previous review.
- Tools and loop: the fifth tool call is refused; the step cap forces the end;
  `need_detail` refuses a Need outside the unused list; disabled, timeout,
  malformed and step-cap paths each store `code_only` with the right reason and
  no agent findings; a successful loop stores `reviewed_by="agent"` and its
  `tool_calls`.
- `accept_review`: unknown need ids and verdicts handled as above; no model
  field reaches a code-computed field.
- Fingerprint: a changed `demand_score` makes the review stale.
- Stages: `stage_reached` → `plo_review` for a current review, back to
  `plo_synthesis` for a stale one; `DESIGNER_STAGES` contains it;
  `test_session_stage_mapping` passes in both directions on the new graph.
- Graph: edges `review_plos_node → plo_report → plo_review → END`, no interrupt
  after `review_plos_node`.
- Routes: `report/run` does not call the review; `PLOReportResponse` has no
  review fields; `review/run` with the slot disabled answers 202 and its job
  stores a `code_only` review; 422 with no PLOs; a stored review without the new
  fields still reads.

Frontend: `npm run lint` and `npm run build` pass.

Live (controller): run the QA agent on `program` (translation, never measured)
and `program-2`; record time, tool calls used, and what it found in a "Measured"
section here.

## Measured

2026-10-13, `z-ai/glm-5.3-flash` on OpenRouter, reasoning bounded at 1024 on
every step, one run per program through `fresh_review` (stored like the job).

| Program | PLOs | Wall time | Steps | Tool calls | Kept | Dropped |
|---|---|---|---|---|---|---|
| `program` (translation) | 7 | 20.4 s | 1 | 0 | 1 redundancy, 7 KSEC (1 disagrees), 0 Bloom, 4 unused verdicts | nothing |
| `program-2` (tourism) | 9 | 21.2 s | 1 | 0 | 2 redundancies, 9 KSEC (1 disagrees), 0 Bloom, 1 unused verdict | nothing |

Both `reviewed_by="agent"`. A full run fits the 300 s budget about 14 times
over, so the step and tool caps, not the timeout, are what bound a run.

What it found:

- **Redundancy.** `program`: PLO2/PLO6/PLO7 — all "translate documents",
  differing in context (legal, business, academic) and tool. `program-2`:
  PLO1/PLO4 (same service, different means) and PLO4/PLO8/PLO9 (the same
  "ดำเนินการ…อย่างมีการวางแผน" shape). PLO4 sits in both groups; `accept_review`
  drops only an identical group, so overlapping groups are kept — advisory,
  and they say different things.
- **KSEC.** One disagreement each: `program` PLO7 K → K+S (the graduate
  translates, which is S); `program-2` PLO7 S → S+C (coordination). Coverage
  is complete on both, no flags; the agent's reading noted E and C share one
  PLO on `program` and K has one PLO on `program-2`.
- **Bloom.** No per-PLO finding on either. The distribution text names the
  apply concentration (5/7, 6/9) and the missing evaluate level for a
  bachelor's program; `below_apply_majority` did not fire on either.
- **Unused Needs.** `program`: 4 out-of-scope Needs, all `ok_to_leave`
  (institutional work, covered by PLO1/PLO5, duplicates PLO2, above bachelor
  level). `program-2`: 1, `ok_to_leave` (covered by PLO5). No unwritten Need
  was selected on either program.

**Open: the tools went unused.** Both runs answered from the dossier alone on
step 1. The dossier is enough for these two sets, so this is not a failure,
but `bloom_lookup`, `check_verbs` and `need_detail` have no live exercise yet —
only unit tests. A set with an unwritten or borderline unused Need, or a
contested verb, is where they would be expected to fire.

## Docs

- `CLAUDE.md`: immutable rule 7 (the waiver and why), the `PLO_REVIEW` slot
  paragraph (stage 06, an agent, runs after the report), the "set review
  advises" pitfall (dossier limits, `code_only`), the 6-stage description at the
  top.
- Skill `references/data-schemas.md`: the new `PLOSetReview` fields.
- `docs/prompt-inventory.md` regenerated (`scripts/dump_prompts.py`).
- `2026-10-04-plo-set-review-design.md`: a note at the top naming what this spec
  replaces.

## Out of scope

- Acting on findings (applying a merge, changing a KSEC or Bloom value).
- A KSEC field on `PLO` (KSEC stays derived from its Needs).
- Stakeholder-group coverage of the set (not chosen).
- Evidence access for the agent.
- Including the review in the Excel export.
