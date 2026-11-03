import { bloomLabel } from '../../constants/bloom'
import type { SupersededPLO } from '../../types/plo'
import type { FeedbackAction, PLOSetReview } from '../../types/ploReview'

const KIND_TH: Record<string, string> = {
  redundancy: 'ซ้ำซ้อน',
  bloom: 'ระดับ Bloom',
  unused_need: 'Need ที่ยังไม่ได้ใช้',
}

const OUTCOME_TH: Record<string, string> = {
  skipped: 'ข้าม',
  failed: 'ไม่สำเร็จ',
}

/** Timestamps arrive both naive (the review) and with an offset (the rest). */
function ms(iso: string): number {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso)
  return Date.parse(hasZone ? iso : `${iso}Z`)
}

function when(iso: string): string {
  const t = ms(iso)
  return Number.isNaN(t) ? iso : new Date(t).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' })
}

interface Round {
  /** The review these actions came from. */
  key: string
  from: number
  /** Start of the next newer round: the window in which this round's replacements were written. */
  until: number
  rows: FeedbackAction[]
}

/** Rows grouped by the review that produced them, newest round first. Within a
 *  round the rows read in action order (oldest first): the list arrives newest
 *  first, so it is reversed before a stable sort on `created_at` settles ties. */
function roundsOf(feedback: FeedbackAction[]): Round[] {
  const byKey = new Map<string, FeedbackAction[]>()
  for (const f of [...feedback].reverse()) byKey.set(f.review_created_at, [...(byKey.get(f.review_created_at) ?? []), f])
  const rounds = [...byKey.entries()]
    .map(([key, rows]) => ({
      key,
      from: ms(key),
      until: Infinity,
      rows: [...rows].sort((a, b) => ms(a.created_at) - ms(b.created_at)),
    }))
    .sort((a, b) => b.from - a.from)
  for (let i = 1; i < rounds.length; i++) rounds[i].until = rounds[i - 1].from
  return rounds
}

function Action({
  row,
  round,
  superseded,
  review,
}: {
  row: FeedbackAction
  round: Round
  superseded: SupersededPLO[]
  review: PLOSetReview
}) {
  // What the new outcome replaced: the snapshots it left, written in this round.
  const before =
    row.outcome === 'applied' && row.result_plo_id
      ? superseded.filter((s) => {
          const at = ms(s.superseded_at)
          return s.cause === 'review' && s.superseded_by === row.result_plo_id && at >= round.from && at < round.until
        })
      : []
  // The level the reviewer asked for is data only on the review itself, and
  // only while that review is the stored one; otherwise just the level reached.
  const asked =
    row.kind === 'bloom' && ms(review.created_at) === round.from
      ? review.bloom.find((b) => b.plo_id === row.plo_ids[0])?.suggested_level
      : null
  const level = row.result_bloom_level

  return (
    <li className="px-4 py-3">
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="chip chip-neutral">{KIND_TH[row.kind] ?? row.kind}</span>
        <span className="data font-semibold text-graphite">{[...row.plo_ids, ...(row.plo_ids.length ? [] : row.need_ids.map((n) => n.slice(0, 8)))].join(' · ')}</span>
        {row.outcome !== 'applied' && (
          <span className={`chip ${row.outcome === 'failed' ? 'chip-mandate' : 'chip-marker'}`}>
            {OUTCOME_TH[row.outcome] ?? row.outcome}
          </span>
        )}
      </p>
      <p className="mt-1 text-sm text-pencil">{row.finding_reason_th}</p>

      {row.outcome === 'applied' ? (
        <div className="mt-2 space-y-1.5">
          {before.map((s) => (
            <p key={s.id} className="rounded-[3px] border border-hair bg-sunk px-3 py-1.5 text-sm text-pencil">
              <span className="data mr-2 text-xs font-semibold">{s.plo.plo_id} · ก่อน</span>
              {s.plo.statement_th}
            </p>
          ))}
          <p className="rounded-[3px] border border-hair-strong bg-sheet px-3 py-1.5 text-sm text-graphite">
            <span className="data mr-2 text-xs font-semibold">{row.result_plo_id} · หลัง</span>
            {row.result_statement_th}
          </p>
          {row.kind === 'bloom' && level && (
            <p className="text-xs text-lead">
              {asked ? `ขอระดับ ${bloomLabel(asked)} · ` : ''}ได้ระดับ {bloomLabel(level)}
            </p>
          )}
        </div>
      ) : (
        row.outcome_reason_th && <p className="mt-2 text-sm text-pencil">{row.outcome_reason_th}</p>
      )}
    </li>
  )
}

/** What the last review sent back for a fix, and what came of it. Older rounds
 *  fold away. Draws nothing when nothing was ever sent back. */
export default function FeedbackTrail({
  feedback,
  superseded,
  review,
}: {
  feedback: FeedbackAction[]
  superseded: SupersededPLO[]
  review: PLOSetReview
}) {
  if (feedback.length === 0) return null
  const [latest, ...older] = roundsOf(feedback)
  // The newest round with rows is not necessarily the stored review's: a review
  // that sent nothing back leaves no rows, and must not look like it did.
  const isCurrent = ms(latest.key) === ms(review.created_at)
  const list = (round: Round) => (
    <ul className="divide-y divide-hair rounded-[4px] border border-hair bg-sunk">
      {round.rows.map((row) => (
        <Action key={row.id} row={row} round={round} superseded={superseded} review={review} />
      ))}
    </ul>
  )

  return (
    <section className="border-t border-hair pt-5" aria-labelledby="feedback-heading">
      <h2 id="feedback-heading" className="section-title">
        ส่งกลับไปแก้แล้ว
      </h2>
      <p className="mt-1 text-xs text-lead">
        {isCurrent ? 'ผลตรวจรอบ' : 'รอบก่อนหน้า · ผลตรวจรอบ'} {when(latest.key)}
        {!isCurrent && ' · ผลตรวจปัจจุบันไม่ได้ส่งอะไรกลับ'}
      </p>
      <div className="mt-3">{list(latest)}</div>
      {older.map((round) => (
        <details key={round.key} className="mt-3">
          <summary className="cursor-pointer text-sm text-pencil">
            รอบก่อนหน้า · {when(round.key)} ({round.rows.length})
          </summary>
          <div className="mt-2">{list(round)}</div>
        </details>
      ))}
    </section>
  )
}
