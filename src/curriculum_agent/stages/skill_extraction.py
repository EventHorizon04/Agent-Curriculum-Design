from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from typing import Any, Literal, get_args

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from curriculum_agent.config import settings
from curriculum_agent.data.prune_cache import EXTRACTION
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    LLMCacheRepository,
    SkillRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_extraction
from curriculum_agent.models import (
    SKILL_KSEC,
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.stages.demand import (
    build_scoring_corpus,
    classification_coverage,
    compute_demand_score,
)
from curriculum_agent.stages.need_grouping import merge_bloom, normalize_need_name

_WS_RE = re.compile(r"\s+")

# Minimum length for a quote to count as evidence. Thai has no inter-word
# spaces, so character count is the available proxy for "this is a phrase, not
# a stray glyph". Below this, a span is so likely to appear in any Thai text by
# chance that matching it proves nothing about whether the skill was invented.
# Tunable: watch the logged drop rate and raise or lower it against real data.
_MIN_SPAN_CHARS = 12


# How much evidence text goes into one extraction call, and how far the next
# window reaches back. The model used to see `raw_text_th[:1200]` and nothing
# else: a twenty-page สภาวิชาชีพ standard was read down to its first paragraph
# and the log said nothing, so the heaviest source in a corpus could yield fewer
# skills than a short job posting. The overlap exists because a window boundary
# lands mid-sentence, and a capability described across it belongs to neither
# window without it — duplicates it creates cost nothing, since the per-evidence
# dedupe collapses them.
_CHUNK_CHARS = 1200
_CHUNK_OVERLAP = 150

# Windows per evidence item. One LLM call each, so this is the ceiling on what a
# single pathological document can cost the corpus — a 200-page PDF pasted into
# one evidence row would otherwise be worth 150 calls on its own. Anything past
# it is reported, never dropped quietly: `chunk_evidence_text` returns how much
# it left unread and `run` logs it against the evidence id.
_MAX_CHUNKS = 12

# A window is only cut back to a word boundary if enough of it survives; below
# this the boundary search is abandoned and the window is cut at the limit.
_CHUNK_MIN_USEFUL = _CHUNK_CHARS // 2


def chunk_evidence_text(text: str) -> tuple[list[str], int]:
    """Split one evidence item into overlapping windows, with what was left out.

    Returns (chunks, characters_unread). Windows are cut back to the last space
    or newline before the limit so a quotable phrase is not split mid-word —
    which matters because `evidence_span_th` has to be copied verbatim, and a
    half-word at the edge of a window is a span the model cannot quote.

    The count of unread characters is returned rather than logged here so the
    caller can name the evidence item it belongs to. It is never silently zero:
    a document longer than _MAX_CHUNKS windows reports exactly what it lost.
    """
    stripped = text.strip()
    if not stripped:
        return [], 0
    if len(stripped) <= _CHUNK_CHARS:
        return [stripped], 0

    chunks: list[str] = []
    start = 0
    # How far the windows have actually read. Not `start`, which the overlap
    # pulls back behind the last window's end — subtracting it would count the
    # overlapped tail as unread when it has been read twice.
    covered = 0
    while start < len(stripped) and len(chunks) < _MAX_CHUNKS:
        end = start + _CHUNK_CHARS
        if end < len(stripped):
            boundary = max(
                stripped.rfind(" ", start, end),
                stripped.rfind("\n", start, end),
            )
            if boundary > start + _CHUNK_MIN_USEFUL:
                end = boundary
            # Absorb a tail shorter than the overlap rather than opening a window
            # for it: that window would be almost entirely re-read text, and it
            # costs a provider call like any other.
            if len(stripped) - end < _CHUNK_OVERLAP:
                end = len(stripped)
        window = stripped[start:end].strip()
        if window:
            chunks.append(window)
        covered = end
        if end >= len(stripped):
            return chunks, 0
        # max(): the window always advances, whatever the boundary search chose,
        # so a pathological text cannot spin here.
        start = max(end - _CHUNK_OVERLAP, start + 1)

    return chunks, len(stripped) - covered


def normalize_for_match(text: str) -> str:
    """Collapse whitespace, trim, lowercase — for substring comparison only."""
    return _WS_RE.sub(" ", text).strip().lower()


def is_grounded(span_th: str, evidence_text: str) -> bool:
    """True when `span_th` really occurs in `evidence_text` and is long enough
    to prove it, not merely disprove nothing.

    Verifies the model quoted rather than invented. Whitespace-insensitive so a
    re-spaced but genuine quote still passes; anything the evidence does not
    contain fails, and the skill is dropped by the caller. Spans shorter than
    `_MIN_SPAN_CHARS` (after normalisation) are rejected outright, since a
    single character or punctuation mark occurs in almost any real evidence
    text by chance and would otherwise pass without proving the quote is real.
    """
    span = normalize_for_match(span_th)
    if len(span) < _MIN_SPAN_CHARS:
        return False
    return span in normalize_for_match(evidence_text)


class _SkillItem(BaseModel):
    skill_name_th: str = Field(min_length=1)
    skill_name_en: str | None = None
    ksec_category: Literal["K", "S", "E", "C"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
    evidence_span_th: str = Field(min_length=_MIN_SPAN_CHARS)
    is_field_relevant: bool = True
    is_graduate_capability: bool = True
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    @field_validator("skill_name_th", "evidence_span_th", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        """Strip before min_length runs, so a whitespace-only value fails
        validation (Instructor reasks) instead of passing as a non-empty string."""
        return v.strip() if isinstance(v, str) else v


class _ExtractedSkillsResponse(BaseModel):
    skills: list[_SkillItem]


# `_SkillItem.ksec_category` is the actual enforcement of the SKILL_KSEC
# invariant documented in models.py (a skill carries K/S/E/C, never the
# Need-level EC) — this asserts the two cannot silently drift apart, the same
# guard shape `prompts/summarize_need.py` uses for `_KSEC_LABEL_TH`.
_skill_ksec_literal = set(get_args(_SkillItem.model_fields["ksec_category"].annotation))
_expected_skill_ksec = {c.value for c in SKILL_KSEC}
if _skill_ksec_literal != _expected_skill_ksec:
    raise AssertionError(
        f"_SkillItem.ksec_category {sorted(_skill_ksec_literal)} has drifted from "
        f"models.SKILL_KSEC {sorted(_expected_skill_ksec)}"
    )


def _extraction_contract_fingerprint() -> str:
    """Short hash of everything that decides the SHAPE of a cached extraction.

    The LLM cache is keyed on the evidence text and the model, so before this
    existed a change to the response schema or the prompt left old entries
    matching. A stale payload was then replayed into the current schema and blew
    up the stage — which is exactly what happened when `evidence_span_th` was
    introduced and 18 cached rows still carried the pre-change fields.

    Deriving the fingerprint from the schema and the prompt rather than hand-
    maintaining a version integer means a future contributor cannot forget to
    bump it: change either one and the key changes with it.
    """
    schema = json.dumps(_ExtractedSkillsResponse.model_json_schema(), sort_keys=True)
    # The system message carries every instruction; only the user message varies
    # per evidence item, so an empty text is enough to capture the contract.
    system_prompt = build_extract_skills_prompt("", "")[0]["content"]
    return hashlib.sha256(f"{schema}\x00{system_prompt}".encode()).hexdigest()[:16]


_EXTRACTION_CONTRACT = _extraction_contract_fingerprint()


def classify_skills(
    raw_skills: list[dict[str, Any]],
    evidence_class_by_id: dict[str, str],
) -> dict[str, str]:
    """Classify every extracted skill name, once the whole corpus is in hand.

    Returns a mapping from *display* skill name to SkillClassification. Names are
    matched after normalize_need_name, the same normaliser dedupe_with_bloom_max
    uses to collapse duplicates into one Need — two spellings that end up in the
    same Need therefore also share a class here.

    Runs after the extraction loop by necessity: need vs want is decided by how
    many distinct evidence items name a skill, which is not knowable while the
    corpus is still being read.

    Precedence, highest first:
      1. named by requirement evidence  → requirement
      2. name matches such a skill      → requirement
      3. is_field_relevant is False     → unclassified
      4. named by >1 evidence item      → need
      5. otherwise                      → want

    Rules 1-2 outrank 3 on purpose: a สภาวิชาชีพ mandate or the faculty's own
    vision stays in the pipeline whatever the extraction model thought of its
    field fit. Dropping it would be the code overruling a legal requirement.
    """
    eids_by_name: dict[str, set[str]] = {}
    relevant_by_name: dict[str, bool] = {}
    display_by_name: dict[str, str] = {}
    requirement_names: set[str] = set()

    for skill in raw_skills:
        name = str(skill["skill_name_th"])
        norm = normalize_need_name(name)
        if not norm:
            continue
        eid = str(skill["evidence_id"])
        eids_by_name.setdefault(norm, set()).add(eid)
        display_by_name.setdefault(norm, name.strip())
        # Any mention judged on-field keeps the name on-field: one model call
        # calling it off-field does not outvote another that did not.
        relevant_by_name[norm] = relevant_by_name.get(norm, False) or bool(
            skill.get("is_field_relevant", True)
        )
        if evidence_class_by_id.get(eid, "general") == "requirement":
            requirement_names.add(norm)

    classified: dict[str, str] = {}
    for norm, eids in eids_by_name.items():
        display = display_by_name[norm]
        if norm in requirement_names:
            classified[display] = "requirement"
        elif not relevant_by_name[norm]:
            classified[display] = "unclassified"
        elif len(eids) > 1:
            classified[display] = "need"
        else:
            classified[display] = "want"
    return classified


def _compute_skill_importance(
    raw_skills: list[dict[str, Any]],
    stakeholder_type_by_evidence: dict[str, str],
) -> dict[str, float]:
    """Per-skill-name demand, computed before Need grouping (a later stage).

    Same weighting as Need.demand_score (compute_demand_score from
    curriculum_agent.stages.demand), grouped by the same normalised name
    (normalize_need_name) that need_grouping.dedupe_with_bloom_max later collapses
    duplicates by — so two spellings of one skill that land in the same Need also
    get the same importance_score here. Keyed by normalised name; the caller must
    normalise before looking a score up.
    """
    eids_by_name: dict[str, set[str]] = {}
    for s in raw_skills:
        norm = normalize_need_name(s["skill_name_th"])
        eids_by_name.setdefault(norm, set()).add(str(s["evidence_id"]))

    return {
        name: compute_demand_score(sorted(eids), stakeholder_type_by_evidence)
        for name, eids in eids_by_name.items()
    }


async def run(state: AgentState) -> AgentState:
    """Stage 2: extract skills from evidence via the light LLM (grounded, cache-first).

    Grouping into Needs is a separate stage (need_combination); this stage only
    extracts and persists ExtractedSkill rows.
    """
    program_id = state.get("program_id", "unknown")
    classified = state.get("classified_evidence")
    if classified is None:
        # Reached without stage 1 in the same run: the /needs REST routes load
        # the corpus themselves, and a graph session that starts here has to do
        # the same or it extracts from nothing. An *empty* list is a different
        # thing and is rejected below — stage 1 having found no evidence must not
        # be answered by re-reading rows it already decided about.
        stored = await EvidenceRepository().list_by_program(program_id)
        classified = [e.model_dump(mode="json") for e in stored]
        logger.info(f"Stage 2: loaded {len(classified)} evidence items from storage")
    if not classified:
        raise ValueError(
            "ไม่มี evidence สำหรับโปรแกรมนี้ กรุณาเพิ่ม evidence "
            "ที่ขั้น Stakeholder Needs ก่อนรัน Skill Extraction"
        )
    metadata = state.get("metadata") or {}
    field_th = str(metadata.get("field", ""))
    program_name_th = str(metadata.get("name_th", ""))
    # Empty for every program whose designer left it blank, which reproduces the
    # pre-scope prompt exactly. Never None: the repository normalises the nullable
    # column, and str() here would otherwise hash the word "None" into the key.
    scope_th = str(metadata.get("scope_th") or "")
    logger.info(f"Stage 2: skill_extraction from {len(classified)} evidence items")

    # --- Step 1: LLM skill extraction per evidence item (cache-first) ---
    raw_skills: list[dict[str, Any]] = []
    dropped_ungrounded = 0
    dropped_too_short = 0
    dropped_not_found = 0
    collapsed_duplicates = 0
    _cache = LLMCacheRepository()

    evidences = [StakeholderEvidence.model_validate(d) for d in classified]
    # One call per window of evidence text, all in flight together under a
    # ceiling. Awaiting them one after another costs len(windows) x per-call
    # latency, which a hosted provider makes fatal: ~90s per call over fourteen
    # items overruns the 300s wait_for in api/routes/needs.py several times over.
    _sem = asyncio.Semaphore(max(1, settings.llm_max_concurrency))

    async def _extract_chunk(
        evidence: StakeholderEvidence,
        chunk: str,
        index: int,
    ) -> _ExtractedSkillsResponse | None:
        # The window is what the model reads and therefore what the entry is
        # keyed on — not the evidence id, so two documents sharing a passage
        # share its extraction, and lengthening a document still hits on every
        # window whose text did not move.
        #
        # field_th/program_name_th are in the key, not just the fingerprint: the
        # fingerprint intentionally covers only the schema-and-instructions
        # contract (see _extraction_contract_fingerprint), which does not vary per
        # program, while these two go into the *user* message per call. Without
        # them here, two programs in different fields ingesting the same source
        # text (same สภาวิชาชีพ standard, same scraped posting) would share a
        # cache entry, and the second program would be served skills whose
        # is_field_relevant was judged against the first program's field.
        #
        # settings.extraction_model appears here, in the hit comparison, and in
        # what `set` stores — one name in all three places. It used to be keyed on
        # light_model and stored as heavy_model, which only worked because the two
        # resolved to the same string; the moment they differ every write becomes
        # a permanent miss and the whole corpus is re-extracted on every run.
        # scope_th joins field_th/program_name_th here for the same reason and is
        # appended unconditionally: two programs with different scope statements
        # must not share an entry, and after this change ships there is no older
        # key worth preserving — the new schema field moved _EXTRACTION_CONTRACT,
        # so every row written before it is already a miss. A conditional append
        # would buy back nothing and leave a branch to maintain forever.
        cache_key = hashlib.sha256(
            f"{chunk}\x00{evidence.classification}\x00{settings.extraction_model}"
            f"\x00{_EXTRACTION_CONTRACT}\x00{field_th}\x00{program_name_th}"
            f"\x00{scope_th}".encode()
        ).hexdigest()

        result: _ExtractedSkillsResponse | None = None
        cached = await _cache.get(cache_key)
        if cached is not None and cached[0] == settings.extraction_model:
            try:
                result = _ExtractedSkillsResponse.model_validate_json(cached[1])
                logger.debug(f"Cache hit for evidence {evidence.evidence_id} window {index}")
            except ValidationError as exc:
                # Belt-and-braces: the contract fingerprint should already have
                # missed on any incompatible entry. Treat a surviving one as a
                # miss and fall through to a fresh extraction rather than failing
                # the stage — or silently losing the item — over a cache artefact.
                logger.warning(f"Unusable cache entry for {evidence.evidence_id}: {exc}")

        if result is None:
            messages = build_extract_skills_prompt(
                chunk,
                evidence.classification,
                field_th=field_th,
                program_name_th=program_name_th,
                scope_th=scope_th,
            )
            # Only the provider call is rationed; a cache hit above never waited
            # for a slot it did not need.
            async with _sem:
                try:
                    result = await complete_extraction(_ExtractedSkillsResponse, messages)
                    await _cache.set(
                        cache_key,
                        settings.extraction_model,
                        result.model_dump_json(),
                        kind=EXTRACTION,
                        contract=_EXTRACTION_CONTRACT,
                    )
                except Exception as exc:
                    logger.warning(
                        f"LLM skill extraction failed for {evidence.evidence_id} "
                        f"window {index}: {exc}"
                    )
        return result

    async def _extract_one(
        evidence: StakeholderEvidence,
    ) -> _ExtractedSkillsResponse | None:
        """Every window of one evidence item, merged back into one result.

        Merged rather than deduped here: the caller already collapses repeated
        names within an evidence item, which is also what makes the overlap
        between windows free.
        """
        chunks, unread = chunk_evidence_text(evidence.raw_text_th)
        if unread:
            logger.warning(
                f"Evidence {evidence.evidence_id} is {len(evidence.raw_text_th)} characters — "
                f"read the first {len(evidence.raw_text_th) - unread} in {_MAX_CHUNKS} windows "
                f"and left {unread} unread. Split the source into separate evidence items, or "
                "raise _MAX_CHUNKS in stages/skill_extraction.py."
            )
        if not chunks:
            return None

        parts = await asyncio.gather(
            *(_extract_chunk(evidence, chunk, i) for i, chunk in enumerate(chunks))
        )
        answered = [p for p in parts if p is not None]
        if not answered:
            # Every window failed. Distinct from an item the model read and found
            # nothing in, which returns an empty response — the caller counts the
            # two differently.
            return None
        return _ExtractedSkillsResponse(skills=[s for p in answered for s in p.skills])

    # Each item's outcome is its own: _extract_chunk swallows provider errors into
    # None, so one bad window cannot take the corpus down. gather preserves input
    # order, which keeps the run reproducible.
    results = await asyncio.gather(*(_extract_one(e) for e in evidences))

    for evidence, result in zip(evidences, results, strict=True):
        if result is not None:
            # Collapse repeated names within this one evidence item, keeping the
            # highest Bloom level (same rule as merge_bloom — the lower level is
            # implied by the higher). Everything else comes from the first
            # occurrence; the alternatives are equally arbitrary and the span and
            # confidence describe the same quoted phrase either way.
            #
            # Deduping is deliberately per-evidence, never across evidence items:
            # two sources naming the same capability are two mentions, and that is
            # precisely the signal Need.freq and demand_score are built from.
            by_norm: dict[str, dict[str, Any]] = {}
            for sk in result.skills:
                if not is_grounded(sk.evidence_span_th, evidence.raw_text_th):
                    dropped_ungrounded += 1
                    if len(normalize_for_match(sk.evidence_span_th)) < _MIN_SPAN_CHARS:
                        dropped_too_short += 1
                        reason = "span too short to prove anything"
                    else:
                        dropped_not_found += 1
                        reason = "quoted text not found in evidence"
                    logger.debug(
                        f"  dropped ungrounded skill '{sk.skill_name_th}' "
                        f"from {evidence.evidence_id} ({reason})"
                    )
                    continue

                norm = normalize_need_name(sk.skill_name_th)
                row = {
                    **sk.model_dump(mode="json"),
                    "evidence_id": evidence.evidence_id,
                    "stakeholder_type": evidence.stakeholder_type.value,
                }
                kept = by_norm.get(norm)
                if kept is None:
                    by_norm[norm] = row
                    continue
                collapsed_duplicates += 1
                kept["bloom_level"] = merge_bloom(
                    [BloomLevel(kept["bloom_level"]), BloomLevel(row["bloom_level"])]
                ).value
                logger.debug(
                    f"  collapsed duplicate skill '{sk.skill_name_th}' "
                    f"within {evidence.evidence_id}"
                )
            raw_skills.extend(by_norm.values())

    if dropped_ungrounded:
        total_seen = len(raw_skills) + dropped_ungrounded
        drop_rate = dropped_ungrounded / total_seen * 100
        logger.warning(
            f"Dropped {dropped_ungrounded}/{total_seen} ({drop_rate:.1f}%) skills failing "
            "the groundedness check: "
            f"{dropped_too_short} too-short (span below {_MIN_SPAN_CHARS} chars, likely "
            f"paraphrase/vague quote), {dropped_not_found} not-found in evidence "
            "(likely fabricated)"
        )
    if collapsed_duplicates:
        logger.info(
            f"Collapsed {collapsed_duplicates} duplicate skill name(s) named more than "
            "once by a single evidence item"
        )
    state["dropped_ungrounded_count"] = dropped_ungrounded

    if not raw_skills:
        # Two different situations reach this line, and only one of them is an
        # answer about the evidence.
        #
        # Every item coming back None means no provider call succeeded at all —
        # an exhausted quota, a dead endpoint, a bad key. That is not "this
        # corpus contains no skills", and returning an empty list for it sent
        # the run on to need_combination and then to plo_synthesis, which failed
        # naming a stage that had done nothing wrong. Raise where the cause is
        # known and still in the log above.
        #
        # Anything else — the model read the windows and named nothing, or
        # everything it named failed groundedness — is a real reading, and keeps
        # the original behaviour.
        #
        # Both paths return before delete_by_program: a run that produced
        # nothing must not wipe a previous run's good rows.
        if all(r is None for r in results):
            raise RuntimeError(
                f"สกัดทักษะไม่สำเร็จ: การเรียกโมเดลล้มเหลวทุกรายการ "
                f"({len(evidences)} หลักฐาน) — ตรวจ provider/quota ของ "
                f"{settings.extraction_model} แล้วรันขั้นนี้ใหม่ "
                "(ทักษะที่บันทึกไว้เดิมยังอยู่)"
            )
        logger.warning("Stage 2: no skills extracted — previous rows left untouched")
        state["extracted_skills"] = []
        state["current_stage"] = "skill_extraction"
        return state

    # --- Step 2: classify every skill, then build ExtractedSkill objects ---
    # One pass over `classified` building both per-evidence lookups: the split
    # into two identically-guarded loops was an artefact of Tasks 7 and 8 landing
    # separately, not a deliberate choice.
    evidence_class_by_id: dict[str, str] = {}
    for d in classified:
        eid = d.get("evidence_id")
        if not eid:
            continue
        evidence_class_by_id[str(eid)] = str(d.get("classification", "general"))

    # Built from the skills, not from `classified`: this is the denominator every
    # demand score is a share of, and need_combination builds the same corpus the
    # same way from the same rows. Reading it off the evidence table here instead
    # is exactly what made a skill's importance_score and its Need's demand_score
    # disagree — see build_scoring_corpus.
    scoring_corpus = build_scoring_corpus(
        (str(s["evidence_id"]), str(s["stakeholder_type"])) for s in raw_skills
    )

    importance_by_name = _compute_skill_importance(raw_skills, scoring_corpus)
    class_by_name = classify_skills(raw_skills, evidence_class_by_id)
    # class_by_name is keyed by the first spelling classify_skills happened to see
    # per normalised name; a second evidence item can contribute a differently-
    # cased/spaced spelling of the same skill into raw_skills (the same scenario
    # importance_score already handles below via normalize_need_name), so looking
    # this up by the raw stripped name alone would silently miss it and fall back
    # to "unclassified" — breaking classify_skills's own contract that every raw
    # skill whose name normalises the same receives the same class. Re-index by
    # normalised name once, up front, and look up every skill through it.
    class_by_norm = {normalize_need_name(name): cls for name, cls in class_by_name.items()}

    logger.info(
        f"Stage 2: skill classification {classification_coverage(list(class_by_name.values()))}"
    )

    extracted: list[ExtractedSkill] = []
    for s in raw_skills:
        skill_id = str(uuid.uuid4())
        extracted.append(
            ExtractedSkill(
                skill_id=skill_id,
                program_id=program_id,
                skill_name_th=s["skill_name_th"],
                skill_name_en=s.get("skill_name_en"),
                ksec_category=KSECCategory(s["ksec_category"]),
                bloom_level=BloomLevel(s["bloom_level"]),
                evidence_span_th=s["evidence_span_th"],
                source_evidence_id=s["evidence_id"],
                source_stakeholder_type=StakeholderType(s["stakeholder_type"]),
                classification=class_by_norm.get(
                    normalize_need_name(s["skill_name_th"]), "unclassified"
                ),
                is_field_relevant=bool(s.get("is_field_relevant", True)),
                # Raw per-row flag, like is_field_relevant beside it and unlike
                # `classification` above: two rows for the same skill name may
                # disagree, and need_combination counts rows on purpose.
                is_graduate_capability=bool(s.get("is_graduate_capability", True)),
                extraction_method="llm",
                confidence=s.get("confidence", 0.8),
                importance_score=importance_by_name.get(
                    normalize_need_name(s["skill_name_th"]), 0.0
                ),
            )
        )

    # Replace, don't accumulate: skill_id is a fresh uuid per run and the
    # repository upserts by it, so without the delete a re-run leaves both sets in
    # the table and the Stage 3 skill table shows every skill twice.
    skill_repo = SkillRepository()
    removed = await skill_repo.delete_by_program(program_id)
    if removed:
        logger.info(f"Replaced {removed} skill row(s) from a previous run")
    await skill_repo.bulk_insert(extracted)

    state["extracted_skills"] = [s.model_dump(mode="json") for s in extracted]
    state["current_stage"] = "skill_extraction"
    return state
