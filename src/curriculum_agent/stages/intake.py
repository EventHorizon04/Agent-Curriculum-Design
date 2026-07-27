from __future__ import annotations

from loguru import logger

from curriculum_agent.data.isced import get_detailed_field
from curriculum_agent.data.repositories import EvidenceRepository, ProgramRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import (
    ExtractedMetadata,
    IscedSuggestion,
    MetadataExtractionResult,
    ProgramMetadata,
)
from curriculum_agent.prompts.extract_metadata import build_extract_metadata_prompt
from curriculum_agent.prompts.suggest_isced import build_suggest_isced_prompt


async def run(state: AgentState) -> AgentState:
    """Stage 0: validate ProgramMetadata, persist to Postgres, load evidence into state."""
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run intake stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
    logger.info(f"Intake: program_id={metadata.program_id}, field={metadata.field}")

    program_repo = ProgramRepository()
    await program_repo.upsert(metadata)

    evidence_repo = EvidenceRepository()
    evidence_items = await evidence_repo.list_by_program(metadata.program_id)
    logger.info(f"Intake: loaded {len(evidence_items)} evidence items for classification")

    state["raw_evidence"] = [e.model_dump(mode="json") for e in evidence_items]
    state["current_stage"] = "intake"
    return state


DOC_TEXT_LIMIT = 8_000  # chars of parsed document text fed to the light model

# Character n-gram width used to measure overlap with the source document. Thai
# has no inter-word spaces, so word-level comparison is unavailable; 4 characters
# is long enough that incidental matches are rare and short enough to survive the
# reordering a legitimate paraphrase introduces.
_GROUNDING_NGRAM = 4

# Below this share of its n-grams appearing in the document, a field is surfaced
# for the designer to check. The extraction prompt permits paraphrase, so this is
# deliberately lenient — it is meant to catch invention, not rewording. Tunable:
# watch how often real documents trip it before tightening.
_GROUNDING_FLAG_THRESHOLD = 0.5

_GROUNDED_FIELDS = (
    "vision_th",
    "mission_th",
    "institutional_identity_th",
    "student_identity_th",
)


def _ngrams(text: str, n: int) -> set[str]:
    squeezed = "".join(text.split())
    return {squeezed[i : i + n] for i in range(len(squeezed) - n + 1)}


def grounding_ratio(extracted: str, doc_text: str, n: int = _GROUNDING_NGRAM) -> float:
    """Share of `extracted`'s character n-grams that also occur in `doc_text`.

    A verbatim copy scores 1.0; a reworded but faithful extraction stays high
    because most character runs survive; text with no basis in the document scores
    near zero. Whitespace is stripped entirely so line breaks and bullet layout in
    the source cannot depress the score.

    Returns 1.0 for text shorter than one n-gram — too little signal to judge, and
    flagging it would only add noise.
    """
    needle = _ngrams(extracted, n)
    if not needle:
        return 1.0
    haystack = _ngrams(doc_text, n)
    return len(needle & haystack) / len(needle)


def low_grounding_fields(metadata: ExtractedMetadata, doc_text: str) -> list[str]:
    """Names of populated fields whose text is weakly supported by the document."""
    flagged = []
    for field in _GROUNDED_FIELDS:
        value = getattr(metadata, field)
        if value and grounding_ratio(value, doc_text) < _GROUNDING_FLAG_THRESHOLD:
            flagged.append(field)
    return flagged


async def extract_metadata_from_text(text: str) -> MetadataExtractionResult:
    """Extract university vision/mission/identity from parsed document text.

    Stateless helper for the intake prefill endpoint — no DB access.

    The model is asked only for the four values; how well each is supported by the
    document is measured here, in code. Weakly supported fields are named in the
    result so the intake form can flag them, and never dropped: the prompt allows
    paraphrase, so low overlap is a reason for a human to look rather than grounds
    for the code to overrule the model.
    """
    messages = build_extract_metadata_prompt(text[:DOC_TEXT_LIMIT])
    extracted = await complete_light(ExtractedMetadata, messages)
    flagged = low_grounding_fields(extracted, text)
    if flagged:
        logger.warning(f"Metadata fields weakly grounded in the document: {flagged}")
    return MetadataExtractionResult(**extracted.model_dump(), low_grounding_fields=flagged)


async def suggest_isced(name_th: str, name_en: str, field: str) -> IscedSuggestion:
    """Classify a program into ISCED-F 2013 + suggest standard names.

    The LLM-returned code must exist in the embedded taxonomy. One retry is
    attempted (naming the invalid code) before giving up — field names in
    the result are always overwritten from the taxonomy, since the code is
    the source of truth, not whatever label the LLM produced for it.
    """
    messages = build_suggest_isced_prompt(name_th, name_en, field)
    result = await complete_light(IscedSuggestion, messages)
    taxonomy_field = get_detailed_field(result.isced_code)

    if taxonomy_field is None:
        retry_messages = build_suggest_isced_prompt(
            name_th, name_en, field, retry_invalid_code=result.isced_code
        )
        result = await complete_light(IscedSuggestion, retry_messages)
        taxonomy_field = get_detailed_field(result.isced_code)
        if taxonomy_field is None:
            raise ValueError(
                f"LLM ตอบ isced_code '{result.isced_code}' ซึ่งไม่อยู่ใน taxonomy หลัง retry"
            )

    return result.model_copy(
        update={
            "field_name_en": taxonomy_field.name_en,
            "field_name_th": taxonomy_field.name_th,
        }
    )
