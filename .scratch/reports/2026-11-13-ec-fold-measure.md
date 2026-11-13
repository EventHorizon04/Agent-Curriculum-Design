# Why two of the three EC dimensions fold: measurement (2026-11-13)

Follow-up to `2026-11-11-full-apply-run.md`, where the EC rule's three groups reached the PLOs as two. No code changed. Inputs are the dumps of `program-run-5` (F1) and the four Agent 1+2 runs B1, B2, U1, U2.

## 1. Is the dedup fold stable?

- **Setup:** the ten in-scope, written, pre-merge Needs of F1, in demand order, through `find_duplicate_groups` (5 calls, majority 3) ten times. Copy DB, 50 calls, none failed.
- **Pair N7+N9** (work quality `[EC]` 0.33 + ethics and culture `[E]` 0.08), the fold seen in F1:
  - merged in **3 of 10 votes**;
  - named by 23 of 50 calls (46%), per vote 2, 2, 2, 3, 2, 1, 4, 1, 2, 4.
- **Pair N1+N2** (AI post-editing `[S]` + professional translation `[K]`): merged in 10 of 10 votes, 36 of 50 calls.
- No other pair reached 2 calls in a vote.

The fold sits on the threshold. F1 was one of the roughly three in ten runs where it passes.

## 2. Are the E/C tags right?

- **Setup:** the 75 distinct graduate-side skill names tagged E or C across the five runs, judged by name by one assessor (Fable 5.2, a subagent that was not told the hypothesis), against the project's own definitions. One pass, no second rater, evidence not consulted.
- **Result:**

| judged | names |
|---|---|
| E or C | 53 (71%) |
| of which not a graduate capability (institutional slogans) | 14 |
| S, clear | 6 (8%) |
| S, arguable | 6 |
| mixed (task plus attitude) | 10 |

- 26 of 75 are grey calls. The share that is not E/C is between 9% and 41%; the point estimate is 29%.
- F1 is the worst run: 9 of its 18 E/C names are S or mixed. Three of the four members of its work-quality group are among them (61, 62, 63).
- **The extraction prompt draws no line between S and E/C.** It gives four labels and "pick exactly one". The only working definition (S = doing the profession's work) is in `prompts/plo_review.py`, which extraction never sees. The same task, certifying a legal translation, is tagged E, C and EC in different runs.
- C acts as the residual bucket: labour-market readiness, competitiveness, "driving the national economy".

## Reading

- The review merge in F1 was correct: the work-quality group was mostly evaluation and certification tasks, so its PLO did duplicate the legal-accuracy S outcome. A guard keyed on tags would have blocked a sound merge.
- The dedup fold of work quality with ethics and culture is a borderline judgement the vote passes about three times in ten. It is not a defect of the vote.
- The cause upstream is supported but not proven: with no S vs E/C rule, task-plus-attitude names land in E/C, the EC groups come out as hybrids, and hybrids read like their S neighbours. One assessor and name-only judgement are the limits.

## Next step, if the designer wants it

An extraction-prompt rule for the S vs E/C line (the head of the name decides: a piece of the profession's work is S, a trait or value is E/C; an attitude adverb does not move a task), measured A/B the way the EC rule was: tags on the same evidence, then groups, then whether the EC Needs still fold. The institutional slogans in C are a separate question for the graduate-capability flag.
