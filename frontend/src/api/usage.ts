/** GET /programs/{id}/usage (UsageSummary in src/curriculum_agent/models.py). */
export interface UsageTotals {
  calls: number
  failed_calls: number
  prompt_tokens: number
  completion_tokens: number
  reasoning_tokens: number
  latency_ms: number
}

export interface SlotUsage extends UsageTotals {
  slot: string
}

export interface JobUsage {
  job_id: string
  /** From the jobs row; empty when that row is gone. */
  kind: string
  /** Thai name of the kind, filled by the server; empty for an unknown kind. */
  label_th: string
  started: string
  total: UsageTotals
  by_slot: SlotUsage[]
}

/** Calls made by a graph session ("รันทั้งชุด"): a session row and no job. */
export interface SessionUsage {
  session_id: string
  started: string
  total: UsageTotals
  by_slot: SlotUsage[]
}

export interface UsageSummary {
  total: UsageTotals
  by_slot: SlotUsage[]
  by_job: JobUsage[]
  by_session: SessionUsage[]
}
