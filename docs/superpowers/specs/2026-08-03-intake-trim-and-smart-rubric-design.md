# Intake Trim and the SMART Rubric

**Date:** 2026-08-03
**Status:** Approved design, not yet implemented
**Builds on:** `2026-08-02-stakeholder-classification-redesign-design.md`

## Problem

Two problems that turn out to be one problem.

**Intake asks for things it should not own.** The form collects the program's vision,
mission, and philosophy as plain metadata fields, offers to prefill them by uploading a
university document, and offers to suggest a program name from an ISCED code. The previous
redesign made the institution's own direction statements first-class *evidence* — classified
`requirement`, extracted for skills, traceable from any PLO that answers them. Keeping the
same content as metadata fields alongside that means the institution's voice enters the
pipeline twice, by two mechanisms, with nothing keeping them consistent.

**The SMART gate is a SMAR gate, and its R measures the wrong thing.** `SMARTCheck` has a
`timely` field that no check ever sets — it is hardcoded `True`
(`plo_synthesis.py:208`), as is `achievable`. The soft judge's three verdicts land in
`soft_flags` and never reach `SMARTCheck` at all, so `SMARTCheck.passed` reports success for
a PLO carrying soft flags. And the soft judge's R check asks a light model whether a PLO
statement resembles `metadata.vision_th`, which is both the weakest available evidence of
alignment and the only reason `vision_th` still has to exist.

## The R insight

The project's SMART rubric defines Relevant as three things:

1. connected to and answering stakeholder needs
2. reflecting the professional competencies the labour market asks for
3. consistent with the institution's vision and mission

The first two live in the data already: a PLO's `source_need_ids` resolve to Needs whose
statements say what the market asked for, and whose `demand_score` says how strongly.

The third no longer needs a text comparison. After the previous redesign the institution's
vision enters as `StakeholderEvidence` with `stakeholder_type=INSTITUTIONAL_DIRECTION` and
`classification="requirement"`, and flows down the same path as everything else:

```
evidence(institutional_direction, requirement)
  → ExtractedSkill(classification="requirement")
    → Need(source_stakeholder_types contains institutional_direction)
      → PLO(source_need_ids)
```

So "does this PLO answer the institution's direction?" is answerable in pure code from
`Need.source_stakeholder_types` — a field that already exists — rather than by asking a
model whether two Thai paragraphs feel similar. That removes the last consumer of
`vision_th` and makes the check deterministic at the same time.

One correction to how it is judged: **institutional coverage is a property of the PLO set,
not of each PLO.** Not every outcome must answer the vision; a program whose outcomes
collectively ignore it has a real problem. So this becomes a program-level flag raised once,
not a per-PLO soft flag raised nine times.

## Design

### 1. Remove the ISCED name suggestion

Delete `stages/intake.suggest_isced`, `prompts/suggest_isced.py`, the
`POST /programs/suggest-isced` route and its `SuggestIscedRequest`, and the `IscedSuggestion`
and `SuggestedName` models. Remove the suggestion UI from `Intake.tsx`.

**Kept:** `field`, `isced_code`, `name_th`, `name_en`, and `data/isced.py`. The designer
types the code; `ProgramCreateRequest._validate_isced_code` still rejects one that is not in
the taxonomy. `field` is load-bearing elsewhere — it reaches the skill-extraction prompt as
`field_th`, which is what makes the `is_field_relevant` judgement answerable — so removing it
would silently break the classification pipeline.

### 2. Remove the document upload prefill

Delete the `POST /programs/extract-metadata` route, `prompts/extract_metadata.py`,
`stages/intake.extract_metadata_from_text`, the grounding helpers (`grounding_ratio`,
`low_grounding_fields`, `_ngrams`, `_GROUNDED_FIELDS`, `DOC_TEXT_LIMIT`, and the two
threshold constants), and the `ExtractedMetadata` / `MetadataExtractionResult` models. Remove
the upload UI from `Intake.tsx`.

`parsers/tika_parser.py` is deleted only if nothing else imports it — check before removing,
and say so in the implementation notes either way.

### 3. Remove the five institutional-direction fields

Deleted from `ProgramCreateRequest` and `ProgramMetadata`, from `ProgramTable`, and from the
intake form: `vision_th`, `mission_th`, `philosophy_th`, `institutional_identity_th`,
`student_identity_th`.

`stages/intake.build_institutional_evidence` and `INSTITUTIONAL_FIELDS` go with them — there
is nothing left to convert. `intake.run()` returns to persisting the program and loading its
evidence.

The designer now enters those statements directly at the Stakeholder Needs page, choosing the
`institutional_direction` type. Nothing forces them to: a program with no institutional
evidence is valid, and §4's program-level flag is what tells the designer they left it out.

One Alembic revision drops the five columns. There is no data to migrate — the content's new
home is the `evidence` table, and a program that already has rows keeps them as evidence if
intake previously converted them.

### 4. The SMART soft judge, rewritten to the project's rubric

The rubric, verbatim from the project's definition, is what the prompt must implement:

- **S — Specific:** the statement names the behaviour, skill, or competency expected,
  specifically rather than broadly, anchored on a Bloom action verb.
- **M — Measurable:** the outcome is observable and can actually be assessed with real
  educational instruments, quantitatively or qualitatively.
- **A — Achievable:** realistic for the qualification level, the program's supporting
  resources, and the time available.
- **R — Relevant:** answers stakeholder needs, reflects the competencies the labour market
  asks for, and is consistent with the institution's vision and mission.
- **T — Time-bound:** carries a clear time condition, which for a PLO normally means "by the
  end of the program".

Hard checks (pure code, `smart_rules.py`) are unchanged: `S_VERB`, `M_FORBIDDEN`,
`R_EVIDENCE`. They alone drive the retry loop and escalation.

The soft judge grows from three verdicts to five:

```python
def build_smart_soft_judge_prompt(
    statement_th: str,
    degree_level: str,
    duration_years: int,
    need_statements_th: list[str],
) -> list[dict[str, str]]:
```

| Verdict | Asks |
|---|---|
| `specific_object_ok` | Is the verb's object specific — not "ความรู้", not "ทักษะที่จำเป็น"? |
| `measurable_ok` | Observable *and* assessable with a real instrument (exam, artefact, performance, portfolio)? Absence of a forbidden word is not evidence of this. |
| `achievable_ok` | Is the Bloom level plausible for `degree_level`, and reachable within `duration_years`? |
| `relevant_needs_ok` | Does the statement actually answer the Needs it cites? `need_statements_th` carries them. |
| `time_bound_ok` | **Defaults true.** Fails only when the statement commits to a different horizon ("ภายในปีที่ 2"). A PLO that says nothing about time is correct by convention — the horizon is the end of the program. |

`vision_th` does not appear. R's institutional component moves to §5.

`soft_flags` gains `M_assessable`, `R_needs` (replacing `R_alignment`), and `T_horizon`.

**Soft verdicts now reach `SMARTCheck`,** which they never did before:

```python
smart = SMARTCheck(
    specific=S_VERB not in fails and judge.specific_object_ok,
    measurable=M_FORBIDDEN not in fails and judge.measurable_ok,
    achievable=judge.achievable_ok,
    relevant=R_EVIDENCE not in fails and judge.relevant_needs_ok,
    timely=judge.time_bound_ok,
    notes_th=judge.notes_th,
)
```

This does not make soft criteria blocking — escalation still reads `fails` (hard checks)
only, and an escalated PLO is still kept for human repair. It makes `SMARTCheck.passed`
mean what it says instead of reporting success for a flagged outcome. When the judge call
fails, every soft verdict defaults true and a warning is logged, so an LLM hiccup degrades
toward "not flagged" rather than falsely flagging good work.

### 5. Institutional coverage as a program-level flag

After synthesizing the set, `plo_synthesis.run` checks whether any Need behind any PLO
carries `institutional_direction` in `source_stakeholder_types`. If none does, it logs a
policy warning naming the gap — the same shape as the existing `MIN_NEEDS` floor warning,
and equally non-blocking:

```
"no PLO traces to the institution's own direction — add วิสัยทัศน์/พันธกิจ
 evidence at the Stakeholder Needs stage, or accept at the checkpoint"
```

The warning belongs at the set level because that is where the property is meaningful.

## Testing

- `test_models.py` — the five fields are absent from `ProgramCreateRequest` and
  `ProgramMetadata`; `isced_code` validation still rejects an off-taxonomy code.
- `test_smart_soft_judge_prompt.py` (new) — all five verdicts are requested; the Needs reach
  the user message; `vision` appears nowhere in the built prompt; `duration_years` reaches it.
- `test_smart_retry_loop.py` — soft verdicts map onto `SMARTCheck` (a PLO whose judge returns
  `measurable_ok=False` has `smart_check.measurable is False` while staying unescalated); a
  judge exception leaves every soft field true and adds no flag; hard checks still drive
  escalation alone.
- `test_plo_synthesis` — the institutional-coverage warning fires when no Need carries
  `institutional_direction`, and does not fire when one does.
- `test_intake_evidence.py` — deleted; `build_institutional_evidence` no longer exists. Its
  deterministic-id and whitespace cases die with it, and that is correct: the behaviour is
  gone, not merely untested.
- `test_api_programs.py` — the two deleted routes now 404; program creation succeeds without
  the five fields.
- `test_extract_metadata.py`, `test_isced.py` (the suggestion half) — deleted with the
  features they cover. Keep any case that covers `data/isced.py` taxonomy lookups, which
  survives.
- Migration: an upgrade/downgrade round trip on a database holding a program row.
- `tests/conftest.py`'s `program_metadata` fixture loses the five fields — every stage test
  depends on it, so this is the change most likely to surface stragglers.

## Documentation

`CLAUDE.md` (the intake stage description, `Project layout` if it names deleted modules),
`.claude/skills/curriculum-design-agent/SKILL.md` (pipeline step 1, the SMART rule),
`references/obe-principles.md` (the SMART rubric — this is where the five definitions above
belong, replacing the current text), `references/prompts.md` (delete the two removed prompts,
rewrite the soft-judge section), `references/data-schemas.md` (`ProgramMetadata` and
`SMARTCheck`).

## Out of scope

- Implementing the CHECO and มคอ.2 exporters, which remain stubs behind 501 routes.
- Making institutional evidence mandatory. It stays optional with a warning.
- Any change to the hard checks, the retry loop's mechanics, `MIN_NEEDS`, the KSEC
  invariant, or the agent's scope boundary at PLO.
