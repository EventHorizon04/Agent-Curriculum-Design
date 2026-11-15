# Cache-off lock runs: single vs multi (2026-11-14)

Branch `feat/four-agent-pipeline` at 2830c10 (requirement-citation gate in single mode).
Copy DB `curriculum_phase1`, backend on :8011 with `LLM_CACHE_ENABLED=false`, every slot on
openrouter `z-ai/glm-5.3-flash`. Each run: `evidence_only` copy of `program` (14 evidence
items) in the given `agent_mode`, then needs -> PLOs -> report with no designer action.
Order interleaved S M S M S M. Raw dumps: `lock-<mode>-<n>.json` in the session scratchpad.

Pass criteria: all jobs succeeded; 6-10 core PLOs; every PLO has `source_need_ids` and
`source_evidence_ids`; 0 `smart_escalated`; single additionally `stop_reason=finished` and no
unread evidence.

## Results

| run | program | pass | Needs | Needs citing requirement | PLOs | core | escalated | soft-flagged | prompt tok | calls | failed calls | wall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| single-1 | program-run-2 | **no** | 3 | 3 | 3 | 3 | 0 | 0 | 1.64M | 53 | 1 | 472 s |
| multi-1 | program-run-3 | yes | 12 | 7 | 9 | 9 | 0 | 1 | 2.06M | 287 | 27 | 682 s |
| single-2 | program-run-5 | yes | 10 | 3 | 10 | 8 | 0 | 0 | 2.14M | 72 | 1 | 321 s |
| multi-2 | program-run-6 | yes | 13 | 6 | 8 | 8 | 0 | 1 | 2.31M | 332 | 44 | 812 s |
| single-3 | program-run-7 | **no** | 11 | 2 | 11 | 2 | 0 | 0 | 2.06M | 66 | 2 | 601 s |
| multi-3 | program-run-8 | yes | 12 | 3 | 8 | 8 | 0 | 0 | 2.89M | 393 | 48 | 1123 s |

Multi: 3/3. Single: 1/3.

Single loop details: needs half finished on its own every run (38 / 39 / 46 turns), 0 unread
evidence, 0 requirement items left uncited; PLO half finished every run (14 / 32 / 18 turns).
The requirement refusal never fired.

Cost: per run single used about the same prompt tokens as multi (1.6-2.1M vs 2.1-2.9M) in
about a fifth of the calls, and was faster (321-601 s vs 682-1123 s). Multi's failed-call
count (27-48 per run) is retries inside its voted stages; single had 1-2.

## Why single failed twice: under-citation

Both failures are the same defect: Needs that each cite **one** evidence item instead of
every item that asks for that capability. Code marks a Need optional when a single
non-requirement item backs it (`is_optional_group`), so:

- **single-1** wrote 3 Needs, each citing one `institutional_direction` item. Requirement
  keeps them core, but 3 core < 6, and 11 of 14 items were cited by nothing.
- **single-3** wrote 11 Needs, every one citing one item. The 9 backed by a general item
  became optional; only the 2 citing institutional direction stayed core (2 core PLOs, 9
  optional PLOs).
- **single-2** (pass) cited 2-3 items per core Need across stakeholder groups.

The prompt already states the rule (rule 3: cite every item that asks for the capability;
rule 4: merge the same capability said in different words; "a good set has 6-10 core Needs
asked for by several items"). GLM does not follow it reliably: same prompt, same corpus,
three different shapes.

A diagnostic replay of the needs half (program-run-4, same prompt, steps logged) produced 10
Needs (9 core), 13/14 items cited, requirement cited correctly, so the new requirement rule
is not what causes the collapse.

## Gaps found

- The single loop stores no transcript of its steps, so a failed run cannot be explained
  after the fact. The replay above needed a wrapper script. Persisting each step's action and
  short reasoning would make failures diagnosable.
- Requirement coverage differs: multi's Needs cite requirement evidence 3-7 times per run,
  single's 2-3 (excluding single-1).

## Round 2: single with the core-Need finish gate (703779f)

The designer chose the gate ("Needs must not be fewer than 6"). Three more single runs, same
setup, backend restarted on the new code.

| run | program | pass | Needs | Needs citing requirement | PLOs | core | prompt tok | calls | wall | needs turns | PLO turns |
|---|---|---|---|---|---|---|---|---|---|---|---|
| single-4 | program-run-9 | **no** | 3 | 3 | 3 | 3 | 1.81M | 56 | 552 s | 43 | 11 |
| single-5 | program-run-10 | yes | 9 | 1 | 9 | 9 | 2.18M | 70 | 582 s | 38 | 31 |
| single-6 | program-run-11 | yes | 10 | 3 | 10 | 8 | 2.09M | 67 | 511 s | 41 | 26 |

Single: 2/3 (round 1: 1/3). The single-3 shape (every Need citing one item) did not recur:
core Needs in runs 5 and 6 cite 2-4 items each. n=3 per round, so this is not proof the
gate caused it.

single-4 repeats single-1 exactly: 3 Needs, one per `institutional_direction` item, 11 of
14 items uncited. With 3 core Needs the gate must have refused the first `Finish` (43 turns
against single-1's 38), and the agent finished again without adding Needs. The once-only
refusal does not hold against this mode.

Both 3-Need runs wrote Needs for the requirement items **only**. Hypothesis, unconfirmed:
the requirement-citation rule (2830c10) sometimes makes GLM read the task as "write a Need
per requirement item". Still no step transcript to check it.

## Round 3: hard gate and step records (df0e81b)

The designer approved both: every `Finish` below 6 core Needs is refused (last turn excepted),
and each half's job result carries `steps`, one record per turn.

| run | program | pass | Needs | Needs citing requirement | PLOs | core | prompt tok | calls | wall | needs turns | PLO turns |
|---|---|---|---|---|---|---|---|---|---|---|---|
| single-7 | program-run-12 | yes | 8 | 1 | 8 | 7 | 1.99M | 65 | 492 s | 37 | 26 |
| single-8 | program-run-13 | yes | 9 | 2 | 9 | 8 | 1.94M | 64 | 331 s | 39 | 24 |
| single-9 | program-run-14 | yes | 9 | 2 | 9 | 8 | 1.87M | 62 | 371 s | 39 | 22 |

Single: 3/3. **The gate never fired in these runs**: the step records show each agent read
all 14 items (turns 1-28), saved 8-10 Needs in a row, and its first `Finish` was accepted.
So round 3 does not test the hard refusal. What changed for these agents is the system
prompt only (step 5 now says a finish below six core Needs is not accepted and that every
stakeholder group is a source of Needs). Three runs cannot separate that from chance:
across rounds 1-2 the 3-Need mode appeared in 2 of 6 runs, so three clean runs happen
about 30% of the time with no change at all.

Totals: single 1/3, then 2/3, then 3/3; multi 3/3 (round 1 only).

Still unverified: what the agent does when the hard refusal does fire (unit tests cover the
handler, no live run has hit it), and the cause of the 3-Need mode. The step records will
show both the next time it happens.

## Open decision (superseded by rounds 2 and 3)

Proposed: a second code-side finish refusal in the needs half, mirroring the requirement
gate — when fewer than 6 core Needs exist, refuse the first `Finish` with the list of
single-item Needs and ask the agent to check each against the other evidence items (add a
matching item to `source_evidence_ids`, otherwise keep it as is). The second `Finish` is
accepted, so the agent is never forced to hit a number. It would have caught both failures.
Cost to the research comparison: single moves further from "one prompt only"; the gate must
be named in the write-up. Alternative: no change, and report single's instability as a
result.
