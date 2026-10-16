# PLO QA review: majority of three runs

**Date:** 2026-10-17
**Status:** design approved in conversation; not yet implemented.
**Builds on:** `2026-10-12-plo-qa-agent-design.md` (the stage 06 agent, its
dossier, tools, `accept_review` and storage). Nothing there changes except
where this document says so.

## Why

The QA agent runs at `temperature=0` and still answers differently from run to
run — its hidden reasoning and OpenRouter's routing are outside our control.
On `program-2-run-1`, two consecutive runs pointed at the same PLOs (1, 4, 6, 8,
9) but grouped the redundancies differently: PLO1/PLO4 plus a four-PLO group the
code dropped, then PLO4/PLO9 and PLO6/PLO8. A designer reading one run cannot
tell a finding the model would repeat from one it produced once.

The designer's goal (2026-10-17) is **trustworthy**, not byte-identical: what the
page shows as a finding must be something the agent says repeatedly; a finding
from one run alone is set apart. Pressing "run" again may change details, but
the core should hold.

## Decisions (from the design conversation)

1. **Approach A — self-consistency.** Run the agent three times on the same
   dossier, in parallel, and keep what a majority agrees on. Not chosen: B
   (accumulate runs across presses — needs several presses before anything is
   trustworthy, and resets on every set change) and C (code proposes candidate
   pairs, the agent answers yes/no — only covers redundancy, and the one code
   signal tried for it, shared evidence, measured misleading).
2. **Three runs, majority threshold**, `plo_review_runs` setting, default 3;
   `1` restores today's behaviour exactly.
3. **One successful run is shown, labelled unconfirmed**, rather than dropped.
4. Prompt, tools, dossier and the information-bias rule are unchanged — every
   run sees exactly what one run sees today.

## 1. Flow and failure

`stages/plo_review._review`, when the slot is on:

1. Build the dossier once (unchanged).
2. `asyncio.gather` `settings.plo_review_runs` calls to `run_review_agent` with
   that dossier. Each call keeps its own budget (4 tool calls, 6 steps,
   `plo_review_timeout_seconds`); they share nothing, and none sees another's
   answer.
3. Each finished run goes through `accept_review` as today, giving one judged
   `PLOSetReview` per run, plus its `drops`. A run whose judged review fails
   `has_agent_findings` counts as failed.
4. By the number of successful runs:

| Successful runs | Stored review |
|---|---|
| ≥ 2 | `consensus_review(runs)` |
| 1 | that run's review as-is |
| 0 | `code_only_review`, reason `timeout` if every run timed out, else `failed` |

`runs_requested` and `runs_succeeded` are set on the stored review in every
agent case. `fresh_review`, the routes, the job, the fingerprint, staleness and
the reuse rule (`_worth_reusing`) are unchanged. Wall time stays about one run's
(~20 s measured); tokens triple.

`plo_review_runs` lives in `config.py` beside `plo_review_timeout_seconds`, an
`int` with `ge=1`.

## 2. Consensus rules — `stages/plo_review_consensus.py`

Pure code, no LLM call: `consensus_review(runs: Sequence[PLOSetReview]) ->
PLOSetReview`, given two or more judged reviews of the same dossier.

**Threshold.** `threshold = runs_succeeded // 2 + 1` — more than half of the
runs that succeeded (2 of 3; 2 of 2). Stored on the review as
`agreement_threshold` so the UI does not re-derive it. Every finding carries
`agreed_runs`: how many runs said it. A finding below the threshold is kept,
marked by its count, never deleted.

**Redundancy.**
- Split every group of every run into PLO pairs; a pair counts at most once per
  run. `support(pair)` = number of runs containing it.
- Passing pairs (`support ≥ threshold`) are joined into connected components. A
  component of at most 3 PLOs **in which every pair passed** becomes one
  finding; otherwise each passing pair in it is its own finding. This keeps
  `MAX_REDUNDANCY_GROUP` and never asserts a pair no majority asserted.
- `agreed_runs` of a finding = the minimum support of its pairs.
- `reason_th` / `suggestion_th` come from the run whose group overlaps the
  finding most — most shared PLOs, then fewest PLOs outside the finding, then
  the earlier run.
- Below-threshold pairs not already inside a passing finding are stored as pair
  findings with their support as `agreed_runs`, text from a run containing them.

**KSEC (one entry per PLO, as today).** The suggested set (as a frozenset) most
runs gave. Ties: the set equal to `current`; then the earlier run's.
`agreed_runs` = how many runs gave that set. `current` and `agrees` stay code's.
A disagreement with `agreed_runs < threshold` is not a main finding.

**Bloom.** For each PLO, count the runs that proposed a level different from
`declared`. A finding exists when that count ≥ 1; `agreed_runs` = that count.
Its level is the one proposed most; ties: the level closest to `declared` on
the Bloom order, then the lower. `reason_th` from a run proposing that level.

**Unused Needs.** For each Need in the dossier's unused list, the verdict the
majority of answering runs gave; `agreed_runs` = that verdict's count. No
majority → `verdict=None`, `agreed_runs` = the largest count. Code facts
(statement, demand, exclusion, `unwritten`) are the dossier's, as today.

**Text and per-run fields.** The *representative run* is the one whose findings
match the consensus main findings most (count of passing redundancy findings,
KSEC entries, Bloom findings and unused verdicts it contains; ties: earlier
run). `summary_th`, `coverage_th`, `bloom_distribution_th`, `tool_calls` and
`dropped_findings` are taken from it, so the dropped-findings warning still
describes the summary shown. `model`, `created_at`, fingerprint and the code
facts (`ksec_coverage`, `bloom_histogram`) are identical across runs.

## 3. Stored data (JSONB, no migration)

- `agreed_runs: int = 1` on `RedundancyFinding`, `KsecFinding`, `BloomFinding`,
  `UnusedNeedFinding`.
- On `PLOSetReview`: `runs_requested: int = 1`, `runs_succeeded: int = 1`,
  `agreement_threshold: int = 1`.

A row written before these fields reads as a one-run review whose every finding
passed (1 ≥ 1) — exactly how it is shown today. `program_copy` clones the JSONB
whole, so the fields survive a copy.

## 4. Frontend (stage 06, `PloReview.tsx`)

- **Status line:** when `runs_succeeded ≥ 2`: "ตรวจ {runs_succeeded} รอบ
  แสดงเฉพาะข้อที่ตรงกันอย่างน้อย {agreement_threshold} รอบ". When
  `runs_requested > 1` and `runs_succeeded == 1`: a `notice notice-warn`
  "ได้ผลรอบเดียว ยังไม่ได้ยืนยันซ้ำ". An old one-run review
  (`runs_requested == 1`) shows neither.
- **Per finding:** a small `chip` "ตรงกัน {agreed_runs}/{runs_succeeded}" on
  redundancy, KSEC-disagreement, Bloom and unused-Need findings when
  `runs_succeeded ≥ 2`.
- **Below threshold:** findings with `agreed_runs < agreement_threshold` move
  out of the main lists into one `<details>` at the end, "พบไม่ถึงเกณฑ์ ({N})",
  grouped by kind.
- **Under the summary:** a small line "สรุปจากรอบที่ตรงกับผลรวมมากที่สุด" when
  `runs_succeeded ≥ 2`.
- Types gain the new fields as optional. Mock sample review shows 3/3, 2/3 and
  a below-threshold finding. Existing `index.css` classes only; no Tailwind
  palette colours.

## 5. Tests

- `consensus_review`: passing and failing pairs; a component over 3 split into
  pairs; a 3-PLO component missing one passing pair split into pairs; ties for
  KSEC (current wins), Bloom (closest to declared), unused (no majority → None);
  representative-run choice and the fields taken from it; `agreed_runs` and
  `agreement_threshold` with 3 runs and with 2.
- `_review` with a fake agent: 3 succeed; 2 succeed + 1 fails; 1 succeeds
  (stored as-is, `runs_requested=3`, `runs_succeeded=1`); 0 succeed, split into
  all-timeout → `timeout` and otherwise → `failed`; `plo_review_runs=1` stores
  what today's code stores; the runs are concurrent (a fake that blocks until
  all three have started).
- A stored review without the new fields reads with the defaults.
- Frontend: `npm run lint` and `npm run build`.

## 6. Live measurement (controller)

Run `program-2-run-1` three times through `POST /plos/review/run`. Record wall
time per run and how the main redundancy findings compare across the three.
**Success:** the main redundancy findings are identical across the three, or
differ by at most one finding. Record in a "Measured" section here.

## Measured

2026-10-17, `program-2-run-1`, `z-ai/glm-5.3-flash`, three presses of
`POST /plos/review/run` one after another, three runs each.

| Press | Wall time | Runs | Main redundancy (agreed/3) | Below threshold |
|---|---|---|---|---|
| 1 | 14 s | 3/3 | PLO1-PLO4 (2), PLO4-PLO9 (3) | PLO6-PLO8 (1) |
| 2 | 12 s | 3/3 | PLO1-PLO4 (2), PLO4-PLO9 (2), PLO6-PLO8 (2) | 3 pairs (1 each) |
| 3 | 12 s | 3/3 | PLO4-PLO9 (3) | none |

- **Success criterion not met.** Presses 2 and 3 differ by two main findings
  (PLO1-PLO4, PLO6-PLO8). Presses 1-2 and 1-3 differ by one.
- **What did stabilise:** PLO4-PLO9 is a main finding on every press, and
  KSEC PLO7 → S+C on every press (2/3, 3/3, 3/3). Before the vote, two single
  runs shared no redundancy finding at all.
- **What still flips:** findings the model gives about half the time
  (PLO1-PLO4, PLO6-PLO8, KSEC PLO3 → K+S) land on either side of 2-of-3 from
  press to press; the one unused Need's verdict went `ok_to_leave` (2/3) on
  presses 1-2 and `consider` (2/3) on press 3.
- Wall time fell rather than rose against the single run (~20 s): the three
  runs are concurrent, and each finished on step 1.

Three samples cannot separate a finding the model gives 50% of the time from
one it gives 67%; more runs per press (5, threshold 3) would, at 5× tokens and
about the same wall time. Not changed — left for the designer.

## Docs

- `CLAUDE.md`: the `PLO_REVIEW_PROVIDER` paragraph (three runs, majority,
  `plo_review_runs`) and the "QA review advises" pitfall (consensus is code's;
  below-threshold findings are kept, not shown as findings).
- Skill `references/data-schemas.md`: the new fields.

## Out of scope

- Changing the prompt, tools or dossier.
- Accumulating runs across presses (approach B).
- Any finding becoming an action on a PLO (unchanged: advisory only).
