# Single agent vs multi-agent for PLO synthesis — experiment design

**Date:** 2026-10-13
**Status:** design approved in conversation; not yet implemented.
**Relates to:** `specs/2026-09-09-smart-validation-agent-design.md` (the per-PLO
validator C2 reuses as a role, and the pattern C1/C2 actions follow);
`specs/2026-10-04-plo-set-review-design.md` (the set-level reader whose checks
become one of C2's critics). Neither is changed by this document — the
experiment runs beside production, not inside it.

## Research question

> Holding the model, the tools, the domain rules and the token budget fixed,
> does a role-specialized multi-agent system produce better PLO sets than a
> single agent?

The independent variable is **architecture only**: how the work and the context
are divided. Everything else is equal by construction (see *Parity*), because a
multi-agent system that wins by spending more tokens, or by seeing a rubric the
single agent never saw, answers a different question.

A secondary question rides along as an ablation: **does the SMART validation
agent change the result?** — measured in the production pipeline (C0 vs C0−V)
and inside the multi-agent system (C2 vs C2−V).

## Decisions (from the design conversation)

1. **Question (a), architecture.** Not "agent vs workflow". The current pipeline
   (C0) is kept as a reference point, not as the comparison the paper is about.
2. **Scope: frozen Needs → PLO set.** Every condition starts from the same stored
   Needs. Extraction and clustering are excluded because their run-to-run
   variance is already known to be large (`build_cluster_skills_prompt`
   docstring, 2026-10-04) and would swamp the effect being measured.
3. **Primary outcome: blinded expert preference.** Code metrics, cost and
   stability are secondary; an LLM judge is reported only as a correlate.
4. **C2 topology: role-specialized with a critic panel.**
5. **Data source: undecided.** The harness takes any Needs bundle. A data gate
   (below) must pass before the main run; until then only the pilot runs.
6. **SMART ablation in C0 and C2**, not a full factorial.

## Conditions

| Id | What runs | Answers |
|---|---|---|
| C0 | the production synthesis path, SMART agent on | reference |
| C0−V | the same, validator off (`code_only`) | is the SMART agent worth it in production? |
| C1 | one agent, one context, every tool, the whole rubric | main RQ |
| C2 | Drafter → Validator → Critic panel → Editor | main RQ |
| C2−V | C2 without the Validator role | does C2's gain come from the validator or the critics? |

"Without the SMART agent" means the LLM soft judge and its repair loop are gone.
The pure-code hard checks (`smart_rules.hard_failures`) still run on every
condition's output at the final gate — exactly what `code_only` means in
production. Hard violations will rise without the validator; that is expected
and is not the interesting result. Expert-rated soft quality is.

## Architecture

```
experiments/agent_arch/
  freeze_needs.py  stored program ──► bundle.json  (Needs + cited evidence
                   excerpts + program context; content hash). Read-only,
                   through the existing repositories.
  rubric.py        rubric fragments shared by every condition
  toolbox.py       the one tool set (calls the core's public rule functions)
  budget.py        counting httpx transport under every LLM client: counts,
                   caps, retries — for C0's production calls as well
  conditions/
    c0_pipeline.py   production synthesis core, validator on or off
    c1_single.py
    c2_multi.py      validator role on or off
  final_gate.py    one pure-code judge for every condition's output
  runner.py        bundle × condition × seed → results/<run>.json + trace.jsonl
  blind.py         rater packets: shuffled, anonymised, no traces
  score.py         code metrics + aggregation of expert ratings
```

Principles:

1. **Production is untouched at run time.** No database writes, no graph, no
   API. Input is `bundle.json`, output is files. A result names the bundle hash
   it came from.
2. **Fairness lives in code, not in discipline.** One `toolbox`, one `budget`,
   one `final_gate`. A condition cannot take a shortcut because there is only
   one path.
3. **The final gate records, it never repairs.** A PLO that breaks a hard rule
   at submit counts against its condition. A gate that fixed it would erase the
   difference being measured.

### Production touchpoints: none

The experiment adapts to production rather than the other way round. Nothing in
`src/` changes. Three seams make that possible:

- **C0 runs the real stage.** The harness calls `plo_synthesis.run(state)` with
  `needs` and `metadata` already in the state, so the stage loads nothing
  itself (the "`None` means load it yourself" rule), and patches
  `PLORepository.bulk_insert` / `delete_by_program` and `EvidenceIndex` with
  in-memory versions backed by the bundle — the same seam
  `tests/integration/test_stage_3_plo.py` uses. Every line of production
  synthesis runs: scope filter, unwritten-Need filter, duplicate check, merge
  floor, slot selection, draft, validation.
- **The toolbox calls the rules, not the validator's tools.** The functions in
  `smart_agent_tools` take a per-PLO `ValidationContext`, but they are thin
  presentation over public rule functions — `smart_rules.hard_failures`,
  `bloom_verbs.levels_for_verb` / `are_adjacent` / `verbs_for_level`,
  `scan_statement_verbs`. The toolbox calls those directly. Rules are never
  copied; only the result shapes are the harness's own.
- **Budget is counted below the client.** Production calls go through
  `llm._complete`, which the harness cannot wrap. Instead it patches
  `llm._get_client` / `_get_raw_client` to build `AsyncOpenAI` with an `httpx`
  transport that reads `usage` from every response. One mechanism counts C0's
  production calls and C1/C2's alike. The single-model rule for C0 is applied
  through environment variables when the harness starts.

**Cost: the harness is coupled to production internals** (the patched names
above). A production rename breaks the harness, not production. A harness smoke
test runs C0 on a pilot bundle against a scripted transport and fails loudly on
any missing seam, and every result records the production commit hash it ran
against.

**C2's Validator is the harness's own**, following the `smart_agent` pattern
rather than calling `run_smart_agent`. Production's validator carries its rubric
inside its prompts, where C1 cannot be handed the same text as a fragment, so
reusing it would break parity. Whether production's validator earns its place
is what H4 (C0 vs C0−V) answers, on the real thing.

## Parity

What C1 and C2 know must be identical; only how it is divided may differ.

- `rubric.py` holds the domain rules as named fragments: OBE/Bloom rules, the
  SMART rubric, each critic's checklist, and the set rules (6-10 core,
  `MIN_CORE_AFTER_MERGE`, a Need behind at most one PLO, non-empty trail).
  Fragment text is taken from the existing production prompts where one exists,
  so the experiment does not fork the rules it is testing.
- **Drift test:** every fragment taken from production must appear verbatim in
  the prompts production renders today (`scripts/dump_prompts.py` already
  renders them). When production edits a prompt the test fails, and the
  researcher decides — update the fragment, or pin the experiment to the commit
  it was registered against. Fragments with no production source (the critic
  checklists) are marked as such and exempt.
- C1 receives every fragment in one system prompt. Each C2 role receives only
  its own.
- **Parity test:** the union of fragments across C2's roles equals C1's set.
  For C2−V the union equals C2's minus the SMART rubric fragment. There is no
  C1−V.
- **One action mechanism for both:** JSON-mode structured steps
  (`reasoning_th` then a discriminated `action`), the shape of
  `smart_agent.ValidationStep`. Not native tool calling — some providers lack
  it, and the two conditions must not differ in mechanism.
- **One model** for every role in every condition, at the same temperature.
  For C0 this means pointing `NEED_DEDUP_*`, `PLO_SYNTHESIS_*` and
  `VALIDATION_*` at that model for the run, overriding the per-slot production
  defaults; C0−V sets `VALIDATION_PROVIDER` to the empty string.

## Toolbox

| Tool | Kind | Source |
|---|---|---|
| `get_need(need_id)` | read | existing, generalised to the bundle |
| `get_evidence(evidence_id)` | read | existing; excerpt only, cited evidence only |
| `bloom_lookup(verb_th)` | read | existing |
| `check_hard(statement_th, action_verb_th, need_ids)` | read | existing (`hard_failures`) |
| `list_plos()` | read | new: the current set |
| `check_set()` | read | new, pure code: core count, uncited / doubly cited Needs, Bloom and KSEC distribution |
| `write_plo(need_ids, statement_th, action_verb_th, bloom_level)` | write | new |
| `revise_plo(plo_id, statement_th, action_verb_th, bloom_level)` | write | new |
| `merge_plos(plo_ids, statement_th, action_verb_th, bloom_level)` | write | new |
| `drop_plo(plo_id)` | write | new |
| `submit()` | end | new: hands the set to `final_gate` |

Every write checks its preconditions in code and answers with a reason on
refusal: the trail is non-empty and resolves to bundle Needs; no Need is cited
twice; a merge keeps at most three Needs of one KSEC tag; the core count stays
within `MAX_CORE_PLOS` and does not fall below `MIN_CORE_AFTER_MERGE` unless it
already was. Refusals are counted (a process metric: how often a condition
fights the rules).

## C1 — single agent

One loop, one growing context, every tool. It writes Thai itself through
`write_plo` / `revise_plo`. It stops at `submit` or when the budget runs out, in
which case the set as it stands is submitted for it. The context is not
summarised: an ever-growing context is a property of the single-agent design,
and is what is being measured. A context overflow is recorded as that
condition's failure.

## C2 — role-specialized with critics

```
Drafter ─(parallel, one call per Need)─► drafts
   ▲                                       │
   │ instruction                           ▼
   ├──────── Validator (per PLO, ≤3 repairs) — the smart_agent pattern
   │                                       │
   │                                       ▼
   │         Critic panel ×4 (parallel, one call each, read only) → findings
   │                                       │
   └──── Editor loop: instruct_revision / merge / drop / finish
              touched PLOs → Validator again → critics, round 2 (max 2 rounds)
```

- **Only the Drafter writes Thai.** The Validator and the Editor emit
  instructions; the Drafter executes them. This mirrors production's rule that
  a repair is never written by the model that judged the draft.
- **Critics:** set structure (redundancy, Need coverage — the `plo_review`
  checks), OBE/Bloom (distribution against degree level), assessment (is each
  outcome observable and assessable), มคอ.2/CHECO (KSEC coverage of learning
  outcome domains).
- The Editor sees the critics' findings, not their checklists. That separation
  is the architectural difference from C1.
- **C2−V** skips the Validator step in both rounds; everything else is
  identical.

## Budget

- **Primary comparison is token-matched:** C1 and C2 get the same total token
  cap. **Secondary:** unbounded, with actual spend reported, so a C2 win can be
  attributed to structure or to compute.
- C2's per-role split is fixed in advance from pilot measurements and
  pre-registered; it is not adjusted during the main run. A role that exhausts
  its share is skipped and the pipeline continues with what exists.
- **Ablations are not token-matched.** C2−V keeps every other role's share and
  the Validator's share is simply unused; C0−V runs as production does. Cost is
  reported beside quality.

## Runs and selection

- k = 5 seeds per (bundle, condition), for stability metrics.
- For expert rating, **one run per (bundle, condition) is drawn at random with a
  seed fixed before any run happens.** Never the best run.
- Conditions are interleaved round-robin, never run one condition to
  completion and then the next, so provider drift spreads across all of them.

## Evaluation

### Primary — pairwise preference (H1, H2)

For each bundle, a rater sees the C1 set and the C2 set side by side, order
randomised as A/B, plus the bundle's Needs. They choose A, B or tie, with a
short reason.

- **H1:** C2 is preferred over C1 under the token-matched budget.
- **H2:** as H1, unbounded.

### Secondary — Likert per set (all conditions)

| Level | Dimensions (1–5) |
|---|---|
| Per PLO | specific, assessable, Bloom level fits the degree, answers its cited Needs, within the profession's scope |
| Set | covers the Needs, non-redundant, KSEC/Bloom balance |
| Usability | "could be submitted in a มคอ.2": as is / minor edits / major edits / unusable |

- **H3:** C2 and C1 differ in cost per unit quality.
- **H4:** C0 rates above C0−V. **H5:** C2 rates above C2−V. H4 and H5 are
  reported as **exploratory**: Likert has less power than pairwise and n is
  small.

Raters see the Needs, never traces, and never which condition produced a set.

### Rater load — balanced incomplete block

Five sets × eight bundles is about ten hours per rater. Instead, each rater
gives Likert ratings to three of the five conditions per bundle, rotated so
every condition is rated equally often across raters; every rater still does
all C1-vs-C2 pairs. About 24 sets + 8 pairs, roughly 6–7 hours each. At least
**five raters** so each (bundle, condition) gets three or more ratings. A
calibration session on pilot bundles comes first. Agreement: Krippendorff's α
(Likert), Fleiss' κ (preference).

### Code metrics (every run, every seed)

- **Correctness:** hard violations at submit, trail integrity, core count in
  band, uncited and doubly cited Needs.
- **Process:** refused tool actions, repair rounds.
- **Cost:** tokens, calls, wall-clock.
- **Stability:** variance across seeds; agreement of the Need→PLO mapping
  between runs (Jaccard over merge groups).

### LLM judge

A model from a different family than the one under test, given the expert
rubric. Reported only as its correlation with the expert ratings — evidence for
whether later work could use it in place of raters. It does not answer the RQ.

### Statistics and sample size

- Mixed-effects logistic regression on preference with random effects for rater
  and bundle; a binomial sign test across bundles as a sanity check.
- Stated plainly: 8 bundles × 3 raters = 24 judgements detects only a large
  effect (C2 preferred ≈75% of the time) at power ≈0.7, and judgements by one
  rater across bundles are not independent, so the effective n is lower.
  Detecting a medium effect needs 15–20 bundles.
- **Pre-registration** (e.g. OSF) before the main run: hypotheses, primary
  outcome, run-selection rule, exclusion rules, maximum infra reruns.
- **Pilot:** one or two bundles, used to set the C2 budget split and calibrate
  the rubric, excluded from the main analysis.

## Data and ethics

- `bundle.json` holds Needs, excerpts of the evidence they cite, and the program
  context (field, degree level), plus a content hash every result cites.
- **Bundles built from internal documents never enter git.** They live outside
  the repository, or are ignored by basename (the CLAUDE.md seed-data pitfall).
  Bundles built from public sources may be committed.
- **Sending excerpts to hosted providers is itself a disclosure.** Every
  condition sends evidence excerpts to OpenRouter / OpenTyphoon. The
  institution's permission must cover that, not only publication; otherwise the
  model under test runs on local Ollama.
- Institution names are anonymised in any published bundle.
- Raters sign a consent form and are reported anonymously. If the researcher's
  institution requires ethics review for expert raters, it is obtained before
  rating starts.
- **Data gate before the main run:** at least 8 bundles; at least 2 from fields
  with a professional council and 2 without; provenance and permission recorded
  for each. Failing the gate, only the pilot runs.

## Error handling

| Event | Handling |
|---|---|
| Provider error, rate limit, timeout | retry with backoff inside `budget`; if still failing, an **infra failure** — rerun with the same seed, not counted against the condition (max reruns pre-registered) |
| Budget exhausted, context overflow, malformed loop, no submit | a **condition outcome** — the current set goes to `final_gate` |
| Provider model drift | model id, provider and timestamp recorded per call; round-robin interleaving |
| LLM cache | **disabled** for every experiment call, so no condition is served an answer another paid for |
| Runner crash | each (bundle, condition, seed) result is written atomically; a rerun skips existing files |

Every prompt and response goes to `trace.jsonl`, for audit and for reviewers.

## Testing

- **Unit:** each write tool's preconditions; `final_gate`; `budget` cuts exactly
  at the cap; the **rubric parity test** (including the C2−V case); `blind.py`
  leaks no condition id or trace detail into a rater packet.
- **Drift:** the rubric drift test above.
- **Integration:** a scripted transport drives C1, C2 and C2−V end to end, and
  C0 / C0−V through the real `plo_synthesis.run` — which doubles as the seam
  smoke test.
- **Budget:** the counting transport sees every call, including production's,
  and a cap cuts at exactly the configured number.
- **Replay:** feeding a recorded trace back reproduces the same final set.
- **Dry run:** a tiny budget on a pilot bundle before every real run.

## Limitations to report

- **Style can leak through blinding.** If C2 writes systematically shorter or
  longer statements than C1, raters may infer the source. It cannot be hidden;
  mean statement length per condition is reported.
- **One model.** The result holds for the model tested; a different model may
  favour a different architecture.
- **Thai, one domain.** Generalisation beyond Thai OBE curriculum design is not
  claimed.
- **Small n** (above), and H4/H5 are exploratory.

## Out of scope

- Extraction and clustering as agents (the earlier per-stage-agent idea). A
  candidate follow-up once this result exists.
- The production critic panel. If C2 wins, this experiment is the evidence for
  moving its design into `plo_synthesis`; that is a separate spec.
- A full 2×2 factorial of architecture × validator.
- Any change to immutable rules 1–8. The experiment applies them through the
  final gate; it does not relax them.
