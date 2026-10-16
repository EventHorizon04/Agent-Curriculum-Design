/**
 * The closing-stage QA review, as `GET /programs/{id}/plos/review` sends it
 * (PLOSetReview in src/curriculum_agent/models.py).
 *
 * Every vocabulary field is a plain `string`, as it is on the model: a stored
 * row must stay readable if a code (a flag, an exclusion, a verdict) is renamed,
 * so the page maps the codes it knows and shows the rest as they are.
 */

export interface RedundancyFinding {
  plo_ids: string[]
  reason_th: string
  suggestion_th: string
  /** Runs (of those with a usable answer) that reported this finding. 1 on old rows. */
  agreed_runs?: number
}

export interface KsecFinding {
  plo_id: string
  /** Computed in code from the PLO's Needs. */
  current: string[]
  suggested: string[]
  /** Computed in code: `current` equals `suggested`. */
  agrees: boolean
  reason_th: string
  /** Runs (of those with a usable answer) that reported this finding. 1 on old rows. */
  agreed_runs?: number
}

export interface BloomFinding {
  plo_id: string
  declared: string
  suggested_level: string | null
  reason_th: string
  /** Runs (of those with a usable answer) that reported this finding. 1 on old rows. */
  agreed_runs?: number
}

export interface UnusedNeedFinding {
  need_id: string
  statement_th: string
  demand_score: number
  ksec_category: string
  stakeholder_types: string[]
  /** `lost_on_demand` | `out_of_scope` | `unwritten`. */
  exclusion: string
  /** True when the Need's sentence is a `[ต้องทบทวน]` fallback, not a written Need. */
  unwritten?: boolean
  /** `consider` | `ok_to_leave` | null (the reviewer did not answer). */
  verdict: string | null
  reason_th: string
  /** Runs (of those with a usable answer) that reported this finding. 1 on old rows. */
  agreed_runs?: number
}

export interface ReviewToolCall {
  tool: string
  arg: string
}

export interface PLOSetReview {
  program_id: string
  plo_fingerprint: string
  /** Empty for a code-only review. */
  model: string
  /** Naive UTC: no offset on the wire. */
  created_at: string
  redundancies: RedundancyFinding[]
  ksec: KsecFinding[]
  bloom: BloomFinding[]
  bloom_distribution_th: string
  summary_th: string
  /** Counts include optional PLOs. */
  ksec_coverage: { counts: Record<string, number>; missing: string[]; flags: string[] }
  bloom_histogram: { counts: Record<string, number>; degree_level: string; flags: string[] }
  coverage_th: string
  unused_needs: UnusedNeedFinding[]
  /** `agent` | `code_only`. */
  reviewed_by: string
  /** `disabled` | `failed` | `timeout`; null when an agent answered. */
  code_only_reason: string | null
  tool_calls: ReviewToolCall[]
  /** Agent entries the code refused, by kind (`redundancy` | `ksec` | `bloom` | `unused`). */
  dropped_findings?: Record<string, number>
  /** Agent runs asked for / with a usable answer / needed to agree. 1 on old rows. */
  runs_requested?: number
  runs_succeeded?: number
  agreement_threshold?: number
}

export interface PLOReviewResponse {
  review: PLOSetReview | null
  /** The PLOs or Needs changed after this review was made. */
  stale: boolean
  review_enabled: boolean
}
