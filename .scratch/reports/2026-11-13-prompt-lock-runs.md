# Prompt-lock candidate: three full runs after the S vs E/C rule (2026-11-13)

At a861a4c (extraction rule added). Copy DB, apply loop (default), GLM on every slot. Each run is an evidence-only copy of `program` (`program-run-6`, `-7`, `-8`), run back to back through `POST /needs/run` then `POST /plos/run`.

Pass criteria, chosen by the builder for Research Plan phase 1 ("complete, cites evidence, right format"): every job succeeded; 6-10 core PLOs; every PLO has `source_need_ids` and `source_evidence_ids`; no `smart_escalated` PLO.

| run | jobs | core PLOs | trail complete | escalated | review rounds | prompt tokens | wall time |
|---|---|---|---|---|---|---|---|
| 1 (run-6) | 4/4 | 7 | yes | 0 | 2 reviews, 1 send-back, stopped: nothing applicable | 1.99M | ~13 min |
| 2 (run-7) | 4/4 | 9 | yes | 0 | 2 reviews, 1 send-back, stopped: nothing applicable | 2.59M | ~17 min |
| 3 (run-8) | 4/4 | 7 | yes | 0 | 5 send-backs, stopped at the cap | 3.61M | ~31 min |

All three pass. Every PLO was judged by the SMART agent (`smart_validated_by=agent`).

## Caveat: Agent 1 ran once, not three times

Runs 2 and 3 made **no extraction and no clustering calls** (usage by slot: 0 and 0, against 15 and 5 in run 1). The extraction and clustering caches are keyed on the evidence text, program name, field, model and prompt contract; an evidence-only copy matches all of them, so runs 2 and 3 replayed run 1's skills and groups. These three runs measure the stability of Need sentences → PLO synthesis → review, not of the extraction prompt that was just changed, nor of the clustering.

The same applies to any repeated-run measurement in the Research Plan (self-similarity across runs 1-3, phase 2's 54 runs): with the cache on, the upstream half of the pipeline is identical by construction and the system looks more stable than it is. Not fixed; a research-run switch that bypasses the cache is the obvious remedy and is the designer's call.

## Observations

- **Core count varies 7 / 9 / 7** on identical skill groups. The variation comes from Need sentences, the dedup vote and the review loop.
- **Run 3's loop did not converge.** It ran the full 5 send-backs (23 min of review): redundancy merges in round 1, then alignment and Bloom redrafts in rounds 2-5, each round finding something new on a different PLO. The decision-28 guard and the merge-drift guard both fired. The cap did its job; the set it ended on still passed.
- **Attitude PLOs:** run 1 had one (EC, cross-cultural communication), with ethics folded into the legal-certification S PLO again; run 2 had three (E, EC, C+S); run 3 had three (C, EC, E+S). The C Need in the top demand slot is a different sentence each run ("[ต้องทบทวน]" marker in run 1, entrepreneurship in run 2, adapting to change in run 3), so whether C reaches a PLO depends on how that sentence is written.
