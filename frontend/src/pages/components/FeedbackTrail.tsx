import { bloomLabel } from '../../constants/bloom'
import type { SupersededPLO } from '../../types/plo'
import type { FeedbackAction, PLOSetReview } from '../../types/ploReview'
import { KIND_TH, OUTCOME_TH, jobIsFor, jobsOf, ms, type Job, type Round } from './feedbackJobs'

function when(iso: string): string {
  const t = ms(iso)
  return Number.isNaN(t) ? iso : new Date(t).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' })
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
  const finding =
    row.kind === 'bloom' && ms(review.created_at) === round.from
      ? review.bloom.find((b) => b.plo_id === row.plo_ids[0])
      : undefined
  const asked = finding?.suggested_level ?? null
  const level = row.result_bloom_level

  return (
    <li className="px-4 py-3">
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="chip chip-neutral">{KIND_TH[row.kind] ?? row.kind}</span>
        <span className="data font-semibold text-graphite">{[...row.plo_ids, ...(row.plo_ids.length ? [] : row.need_ids.map((n) => n.slice(0, 8)))].join(' · ')}</span>
        {row.outcome !== 'applied' && (
          <span className={`chip ${row.outcome === 'failed' ? 'chip-mandate' : row.outcome === 'planned' ? 'chip-neutral' : 'chip-marker'}`}>
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
              {finding?.suggested_verb_th ? `แนะนำกริยา: ${finding.suggested_verb_th} · ` : ''}
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

function RoundList({ round, superseded, review }: { round: Round; superseded: SupersededPLO[]; review: PLOSetReview }) {
  return (
    <div>
      {round.n > 0 && <h3 className="eyebrow">รอบที่ {round.n}</h3>}
      {round.rows.length > 0 && (
        <ul className="mt-1.5 divide-y divide-hair rounded-[4px] border border-hair bg-sunk">
          {round.rows.map((row) => (
            <Action key={row.id} row={row} round={round} superseded={superseded} review={review} />
          ))}
        </ul>
      )}
      {round.stop && (
        <p className="mt-1.5 text-sm text-pencil">
          <span className="chip chip-neutral mr-2">หยุด</span>
          หยุดเพราะ: {round.stop.outcome_reason_th}
        </p>
      )}
    </div>
  )
}

function JobBody({ job, superseded, review }: { job: Job; superseded: SupersededPLO[]; review: PLOSetReview }) {
  return (
    <div className="space-y-4">
      {job.rounds.map((round) => (
        <RoundList key={round.n} round={round} superseded={superseded} review={review} />
      ))}
    </div>
  )
}

const jobStart = (job: Job): string => when(new Date(job.rounds[0].from).toISOString())

/** What the last review job sent back for a fix, round by round, and what came
 *  of it. Older jobs fold away. Draws nothing when nothing was ever sent back. */
export default function FeedbackTrail({
  feedback,
  superseded,
  review,
}: {
  feedback: FeedbackAction[]
  superseded: SupersededPLO[]
  review: PLOSetReview
}) {
  const [latest, ...older] = jobsOf(feedback)
  if (!latest || latest.rounds.length === 0) return null
  // The newest job is not necessarily the stored review's: a review that sent
  // nothing back leaves no rows, and must not look like it did.
  const isCurrent = jobIsFor(latest, review.created_at)

  return (
    <section className="border-t border-hair pt-5" aria-labelledby="feedback-heading">
      <h2 id="feedback-heading" className="section-title">
        ส่งกลับไปแก้แล้ว
      </h2>
      <p className="mt-1 text-xs text-lead">
        {isCurrent ? 'ผลตรวจรอบ' : 'รอบก่อนหน้า · ผลตรวจรอบ'} {jobStart(latest)}
        {!isCurrent && ' · ผลตรวจปัจจุบันไม่ได้ส่งอะไรกลับ'}
      </p>
      <div className="mt-3">
        <JobBody job={latest} superseded={superseded} review={review} />
      </div>
      {older.map((job) => (
        <details key={job.key} className="mt-3">
          <summary className="cursor-pointer text-sm text-pencil">
            รอบก่อนหน้า · {jobStart(job)} ({job.rounds.reduce((n, r) => n + r.rows.length, 0)})
          </summary>
          <div className="mt-2">
            <JobBody job={job} superseded={superseded} review={review} />
          </div>
        </details>
      ))}
    </section>
  )
}
