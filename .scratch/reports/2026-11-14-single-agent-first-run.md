# Single-agent mode: first real run (2026-11-14)

At 63ee686. Copy DB `curriculum_phase1` (migrated to `c8e3f4a5b627`), backend on :8011, GLM (`z-ai/glm-5.3-flash`) on the `single_agent` slot, temperature 0, no cache. One `evidence_only` copy of `program` with `agent_mode=single` (`program-run-1`), then `POST /needs/run`, `POST /plos/run`, `POST /plos/report/run` back to back with no designer action in between. Corpus: 14 evidence items, 9,537 characters (every item fits in one 6,000-character part).

## Numbers

| | needs half | PLO half | whole run |
|---|---|---|---|
| stop reason | `finished` | `finished` | — |
| turns (of 80) | 37 | 21 | 58 |
| wall time | 170 s | 95 s | ~4.5 min (report 0 s) |
| evidence unread / text dropped | 0 / 0 | — | — |
| LLM calls | | | 60 (2 failed, both recovered) |
| prompt tokens | | | 1.73M (average ~29k per call) |
| completion tokens | | | 44k (21k of them reasoning) |

The two failed calls are the model's hidden reasoning running into the 8,192-token step cap; the loop re-asked with bounded reasoning and continued, as designed.

For scale, the three multi lock runs of 2026-11-13 (same corpus, same model, older concurrency, Agent 1 replayed from cache in runs 2-3) used 1.99M / 2.59M / 3.61M prompt tokens and 13 / 17 / 31 minutes. They are not a like-for-like comparison: those runs had Agent 1 cached and predate the concurrency change, and single ran no cache at all.

## Output

- **8 Needs: 5 core, 3 optional.** Seven are tagged S, one is E+C (cross-cultural, ethical communication), one is C (adapting and self-directed learning). Classes, derived in code: 5 `need`, 3 `want`, **0 `requirement`**.
- **8 PLOs: PLO1-5 and OPT1-3,** one Need each, every one with a full evidence trail, `smart_validated_by=single_agent`, **0 escalated, 0 soft flags.**
- **Report built** from the stored set.

## What did not go well

1. **Below the 6-10 core band (5).** The code logged the policy warning at both halves. By the pass criteria used for the multi lock runs (6-10 core PLOs), this run **does not pass**.
2. **The institution's direction was never cited.** All three `institutional_direction` items (vision of the university, vision and philosophy of the college: the only `requirement` evidence in the corpus) were read and noted, but no Need cites them, so no Need is `requirement`. Also uncited: the faculty-administrator item, the curriculum-lead item, and the two national-plan items. 7 of 14 items cited. Multi reaches institutional evidence through skill extraction; the single prompt asks for capabilities grounded in evidence and the agent treated mission statements as context rather than a source.
3. **Self-judged soft verdicts were all "pass".** Not one of the seven soft criteria failed on any of the eight PLOs. In the multi runs the voted judges raise soft flags on most sets. Whether single is right or lenient here is exactly what the phase-1 comparison has to measure (LLM-as-a-judge on both sets); it should not be read as single being better.
4. **Verbs.** PLO4 opens with "ปรับตัว" (adapt) declared as apply; OPT1/OPT3 open with "ใช้". The hard check passed them; whether "ปรับตัว" is an assessable outcome verb is a soft judgement the agent did not flag.

## Budgets and settings

- 80 turns per half: used 37 and 21. Adequate for this corpus.
- 1,800 s per half: used 170 s and 95 s.
- Context window setting 128,000 with budget ratio 0.7: average prompt ~29k tokens, no evidence text was dropped. The setting was never exercised, so the real window of `z-ai/glm-5.3-flash` is still **unconfirmed**; the drop logic is covered only by unit tests.

## Next

- Before the cache-off lock runs: decide whether the single prompt should say outright that `institutional_direction` and `professional_council` evidence must be cited by at least one Need when it names a capability (a prompt change, then the inventory is regenerated). This is the designer's call: it moves single toward multi's behaviour, which is a design choice for the comparison, not a bug fix.
- Three cache-off runs per mode for the lock, as planned.
