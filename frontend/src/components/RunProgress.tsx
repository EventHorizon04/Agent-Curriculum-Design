import { useEffect, useState } from 'react'
import type { JobInfo } from '../api/jobs'

/**
 * What a designer sees while a stage runs.
 *
 * A run is a background job and there is no progress stream, so this page cannot
 * say how far along it is, and it does not pretend to: no percentage, and the
 * step list says what the stage does rather than which step it is on. What it can
 * say honestly is how long it has been running and how long a run of this kind
 * usually takes, and that is what a designer staring at it needs to decide
 * whether to wait, or whether something is wrong. The clock counts from the
 * job's own start (`since`), so a page opened mid-run reads the same as the one
 * that started it.
 */
export interface RunPlan {
  title: string
  /** What the stage does, in order, in the designer's words. */
  steps: string[]
  /** Typical duration in seconds, [usual minimum, usual maximum]. */
  typical: [number, number]
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatSpan(seconds: number): string {
  if (seconds < 60) return `${seconds} วินาที`
  const minutes = Math.round(seconds / 6) / 10
  return `${minutes} นาที`
}

/** Seconds since `since` (epoch ms; mount time when omitted), ticking once a
 *  second. Read once: a different run is a different element (the callers key
 *  this by job id), not a moved start. */
function useElapsed(since?: number): number {
  const [start] = useState(() => (since !== undefined && Number.isFinite(since) ? since : Date.now()))
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  return Math.max(0, Math.floor((now - start) / 1000))
}

export default function RunProgress({ plan, since }: { plan: RunPlan; since?: number }) {
  const elapsed = useElapsed(since)
  const [min, max] = plan.typical
  // The scale runs a third past the usual maximum, so a run that is merely
  // slow still has somewhere on the bar to be.
  const scaleEnd = Math.round(max * 1.35)
  const at = Math.min(elapsed / scaleEnd, 1)
  const overdue = elapsed > max

  return (
    <section className="panel overflow-hidden" aria-labelledby="run-progress-title">
      <div className="flex flex-col gap-6 px-5 py-8 sm:flex-row sm:items-start sm:gap-8 sm:px-8">
        <div className="flex items-center gap-4 sm:flex-col sm:items-center sm:gap-3 sm:pt-1">
          <span className="run-dial run-dial-lg" aria-hidden="true" />
          {/* Not announced: a screen reader reading the clock every second is
              noise. The title below is the live region. */}
          <span className="data text-2xl leading-none text-graphite tabular-nums" aria-hidden="true">
            {formatElapsed(elapsed)}
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <p className="eyebrow">กำลังทำงาน</p>
          <h2 id="run-progress-title" className="section-title" role="status" aria-live="polite">
            {plan.title}
          </h2>

          {/* The typical window, with where this run sits in it. */}
          <div className="mt-5" aria-hidden="true">
            <div className="relative h-1.5 overflow-hidden rounded-[2px] bg-sunk ring-1 ring-hair ring-inset">
              <span
                className="absolute inset-y-0 border-x border-stamp/50 bg-stamp/15"
                style={{ left: `${(min / scaleEnd) * 100}%`, width: `${((max - min) / scaleEnd) * 100}%` }}
              />
              <span className="animate-run-sweep absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-stamp/25 to-transparent" />
            </div>
            <div className="relative h-4">
              <span
                className={[
                  'absolute top-0 h-3 w-0.5 -translate-x-1/2 transition-[left] duration-1000 ease-linear',
                  overdue ? 'bg-marker-ink' : 'bg-stamp',
                ].join(' ')}
                style={{ left: `${at * 100}%` }}
              />
            </div>
          </div>
          <p className="text-xs text-pencil">
            ปกติใช้เวลา {formatSpan(min)} – {formatSpan(max)}
            <span className="text-lead"> · ช่วงที่แรเงาบนแถบ</span>
          </p>

          {overdue && (
            <p className="notice notice-warn mt-3">
              นานกว่าปกติแล้ว ระบบยังทำงานอยู่ — ไม่ต้องกดรันซ้ำ ผลจะแสดงที่หน้านี้เมื่อเสร็จ
            </p>
          )}

          <div className="mt-6 border-t border-hair pt-4">
            <p className="eyebrow mb-2">สิ่งที่ระบบทำในขั้นนี้</p>
            <ol className="space-y-1.5">
              {plan.steps.map((step, i) => (
                <li key={step} className="flex gap-3 text-sm text-graphite">
                  <span className="data w-5 shrink-0 text-right text-lead">{i + 1}</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </section>
  )
}

/**
 * How the latest background run of a page ended, when it ended badly.
 *
 * Drawn from the job record, not from anything the page watched happen, so it is
 * still on screen after the designer has gone to another page and come back, or
 * reloaded: a failure that only showed to whoever was looking at the moment it
 * happened would be gone by the time anyone checked. It stays until a newer run
 * of the page's kinds replaces it as the latest.
 */
export function RunFailure({ job, subject }: { job: JobInfo; subject?: string }) {
  const at = job.finished_at ? new Date(job.finished_at) : null
  const time =
    at && !Number.isNaN(at.getTime())
      ? at.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })
      : ''
  return (
    <div className="notice notice-error" role="alert">
      <p className="font-medium">
        {job.label_th || 'งานเบื้องหลัง'}
        {subject && ` ${subject}`} ไม่สำเร็จ
        {time && <span className="font-normal"> · เมื่อ {time}</span>}
      </p>
      {job.error_th && <p className="mt-0.5">{job.error_th}</p>}
    </div>
  )
}

/** A one-line wait, for loads short enough not to need the full panel. */
export function LoadingLine({ label = 'กำลังโหลด…' }: { label?: string }) {
  return (
    <p className="flex items-center justify-center gap-2.5 py-16 text-sm text-pencil" role="status">
      <span className="run-dial" aria-hidden="true" />
      {label}
    </p>
  )
}
