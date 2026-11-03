/**
 * The PLO shapes, in one place.
 *
 * PloSynthesis and PloReport each declared their own copy, and they had already
 * drifted: PloReport's PLO had no `smart_check` at all, so the checkpoint page —
 * the one where "why did this escalate" is the question a designer came to
 * answer — literally could not show the breakdown, even though the field was in
 * the payload all along.
 *
 * There is no test runner in this project, so a shared module is the only
 * mechanical guard against that class of drift.
 */

export interface SmartFinding {
  criterion: string
  severity: 'hard' | 'soft'
  note_th: string
}

export interface SMARTCheck {
  specific: boolean
  measurable: boolean
  achievable: boolean
  relevant: boolean
  timely: boolean
  notes_th: string | null
  findings: SmartFinding[]
}

/** Which validator produced a verdict — see the Thai labels in constants/smart. */
export type ValidatedBy = 'agent' | 'code_only' | 'stale' | 'legacy'

export interface PLO {
  plo_id: string
  program_id: string
  statement_th: string
  statement_en: string | null
  bloom_level: string
  action_verb_th: string
  smart_check: SMARTCheck
  source_need_ids: string[]
  source_evidence_ids: string[]
  rationale_th: string
  distinctive_feature_th: string | null
  version: number
  smart_retry_count: number
  smart_escalated: boolean
  soft_flags: string[]
  smart_validated_by: ValidatedBy
  smart_diagnosis_th: string | null
  is_optional: boolean
}

/** A PLO a merge replaced, kept so the designer can see what it said. The live
 *  list never contains one. */
export interface SupersededPLO {
  id: string
  program_id: string
  /** plo_id of the outcome that replaced it. */
  superseded_by: string
  /** ISO timestamp with an offset. */
  superseded_at: string
  /** Who replaced it: the designer's merge, or the review's send-back. Null on rows from before the field: the designer. */
  cause?: 'designer' | 'review' | null
  plo: PLO
}
