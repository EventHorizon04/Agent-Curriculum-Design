import type { FeedbackAction } from '../../types/ploReview'

/** Timestamps arrive both naive (the review) and with an offset (the rest). */
export function ms(iso: string): number {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso)
  return Date.parse(hasZone ? iso : `${iso}Z`)
}

export const KIND_TH: Record<string, string> = {
  redundancy: 'ซ้ำซ้อน',
  alignment: 'ความสอดคล้อง',
  bloom: 'ระดับ Bloom',
  ksec_gap: 'หมวด KSEC ที่ขาด',
  unused_need: 'Need ที่ยังไม่ได้ใช้',
}

export const OUTCOME_TH: Record<string, string> = {
  skipped: 'ข้าม',
  failed: 'ไม่สำเร็จ',
  planned: 'จะส่งกลับ (โหมดทดลอง)',
}

export const isLoopEnd = (row: FeedbackAction): boolean => row.kind === 'loop_end'

export interface Round {
  /** The loop's round number, from 1; 0 for rows written before the loop (no round header). */
  n: number
  /** The earliest review these rows came from. */
  from: number
  /** Start of the next newer round: the window in which this round's replacements were written. */
  until: number
  /** The round's actions, oldest first, without the stop row. */
  rows: FeedbackAction[]
  /** The `loop_end` row that stopped the loop in this round. */
  stop: FeedbackAction | null
}

/** One review job: every round it ran, oldest first. */
export interface Job {
  key: string
  rounds: Round[]
}

function roundsOf(rows: FeedbackAction[]): Round[] {
  const byRound = new Map<number, FeedbackAction[]>()
  for (const f of rows) byRound.set(f.round ?? 0, [...(byRound.get(f.round ?? 0) ?? []), f])
  return [...byRound.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([n, list]) => {
      const sorted = [...list].sort((a, b) => ms(a.created_at) - ms(b.created_at))
      return {
        n,
        from: Math.min(...sorted.map((r) => ms(r.review_created_at))),
        until: Infinity,
        rows: sorted.filter((r) => !isLoopEnd(r)),
        stop: sorted.find(isLoopEnd) ?? null,
      }
    })
}

/** The send-back rows grouped into jobs, newest first. A job is the run of rows
 *  from one `loop_end` row back to the previous one (exclusive); rows with no
 *  `loop_end` after them (written before the loop existed) fall back to one job
 *  per review. `feedback` arrives newest first. */
export function jobsOf(feedback: FeedbackAction[]): Job[] {
  const groups: { key: string; rows: FeedbackAction[] }[] = []
  const legacy = new Map<string, FeedbackAction[]>()
  let current: { key: string; rows: FeedbackAction[] } | null = null
  for (const row of feedback) {
    if (isLoopEnd(row)) {
      current = { key: row.id, rows: [row] }
      groups.push(current)
    } else if (current && (row.round ?? 0) > 0) {
      current.rows.push(row)
    } else {
      // Rows from before the loop (round 0) are never part of a loop job.
      legacy.set(row.review_created_at, [...(legacy.get(row.review_created_at) ?? []), row])
    }
  }
  const legacyGroups = [...legacy.entries()].map(([key, rows]) => ({ key, rows }))
  // Newest job first, by its newest row.
  const newest = (g: { rows: FeedbackAction[] }): number => Math.max(...g.rows.map((r) => ms(r.created_at)))
  const jobs: Job[] = [...legacyGroups, ...groups]
    .sort((a, b) => newest(b) - newest(a))
    .map((g) => ({ key: g.key, rounds: roundsOf(g.rows) }))

  // Each round's window ends where the next newer round begins.
  const all = jobs.flatMap((j) => j.rounds).sort((a, b) => b.from - a.from)
  for (let i = 1; i < all.length; i++) all[i].until = all[i - 1].from
  return jobs
}

/** Does this job's last round come from the review that is stored now? */
export function jobIsFor(job: Job, reviewCreatedAt: string): boolean {
  const last = job.rounds[job.rounds.length - 1]
  return last !== undefined && last.from === ms(reviewCreatedAt)
}
