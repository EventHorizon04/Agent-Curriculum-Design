import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import api from '../../api/client'
import { startJob, type JobKind } from '../../api/jobs'
import RunProgress, { RunFailure } from '../../components/RunProgress'
import { PLO_SEND_BACK_PLAN } from '../../constants/runPlans'
import { useJobs } from '../../hooks/useProgramJobs'
import { useReloadOnJobs } from '../../hooks/useReloadOnJobs'
import type { PLO } from '../../types/plo'

/** Jobs after which the PLOs listed here may differ from what was read. */
const RELOAD_KINDS: JobKind[] = ['plo_send_back', 'plo_synthesis', 'single_plos', 'plo_review', 'plo_revalidate']

interface SendBackOutcome {
  plo_id: string
  status: 'rewritten' | 'refused' | 'failed'
  detail_th: string
  result_plo_id: string | null
  result_statement_th: string | null
}

const STATUS_TH: Record<SendBackOutcome['status'], { label: string; cls: string }> = {
  rewritten: { label: 'แก้แล้ว', cls: 'chip-stamp' },
  refused: { label: 'ไม่ได้แก้', cls: 'chip-marker' },
  failed: { label: 'ล้มเหลว', cls: 'chip-mandate' },
}

/** The designer's send-back: tick the PLOs the AI should rewrite, say why for each,
 *  and send them in one job. The reasons are the instruction; nothing here edits a
 *  statement. Used on the PLO checkpoint, with a review or without one. */
export default function SendBackList({ programId }: { programId: string }) {
  const [plos, setPlos] = useState<PLO[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  // plo_id -> reason; a key present means the row is ticked.
  const [picked, setPicked] = useState<Record<string, string>>({})
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState<string | null>(null)

  const { running, latestOf, started, refresh } = useJobs()
  const busy = running !== null || starting
  const mine = running?.kind === 'plo_send_back' ? running : null
  const last = latestOf(['plo_send_back'])

  const latestRead = useRef(0)
  const load = useCallback(async () => {
    const n = ++latestRead.current
    try {
      const res = await api.get<PLO[]>(`/programs/${programId}/plos/`)
      if (n !== latestRead.current) return
      setPlos(res.data)
      setLoadError(false)
      // A PLO that left the set (merged, redrafted) can no longer be ticked.
      const ids = new Set(res.data.map((p) => p.plo_id))
      setPicked((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => ids.has(id))))
    } catch {
      if (n === latestRead.current) setLoadError(true)
    }
  }, [programId])

  const watch = useReloadOnJobs(RELOAD_KINDS, () => void load())

  useEffect(() => {
    void load()
  }, [load])

  const ticked = useMemo(() => Object.keys(picked), [picked])
  const blank = ticked.some((id) => picked[id].trim() === '')
  const canSend = ticked.length > 0 && !blank && !busy

  const toggle = (id: string, on: boolean) =>
    setPicked((prev) => {
      const next = { ...prev }
      if (on) next[id] = prev[id] ?? ''
      else delete next[id]
      return next
    })

  const send = async () => {
    setStarting(true)
    setError('')
    try {
      const job = await startJob(`/programs/${programId}/plos/send-back`, {
        items: ticked.map((id) => ({ plo_id: id, reason_th: picked[id].trim() })),
      })
      setPicked({})
      watch(job)
      started(job)
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response
      const d = res?.data?.detail
      setError(typeof d === 'string' ? d : 'ส่งกลับไม่สำเร็จ')
      if (res?.status === 409) void refresh()
    } finally {
      setStarting(false)
    }
  }

  const outcomes =
    last?.status === 'succeeded' && last.job_id !== dismissed
      ? ((last.result as { outcomes?: SendBackOutcome[] } | null)?.outcomes ?? [])
      : []

  return (
    <section className="panel px-5 py-4" aria-labelledby="send-back-heading">
      <h2 id="send-back-heading" className="section-title">
        ส่งกลับ PLO ให้ AI แก้
      </h2>
      <p className="mt-1 text-xs text-lead">
        เลือกข้อที่ยังไม่พอใจและเขียนเหตุผล — AI จะร่างข้อนั้นใหม่จาก Need เดิม ข้อที่ไม่เลือกจะไม่ถูกแตะ
      </p>

      {last?.status === 'failed' && (
        <div className="mt-3">
          <RunFailure job={last} />
        </div>
      )}

      {mine && (
        <div className="mt-3">
          <RunProgress key={mine.job_id} plan={PLO_SEND_BACK_PLAN} since={Date.parse(mine.created_at)} />
        </div>
      )}

      {outcomes.length > 0 && (
        <div className="mt-3 border-l-2 border-hair-strong bg-sunk px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <p className="eyebrow">ผลการส่งกลับรอบล่าสุด</p>
            <button onClick={() => setDismissed(last?.job_id ?? null)} className="link text-xs">
              ปิด
            </button>
          </div>
          <ul className="mt-1 divide-y divide-hair">
            {outcomes.map((o) => (
              <li key={o.plo_id} className="py-2">
                <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="data font-semibold text-graphite">{o.plo_id}</span>
                  <span className={`chip ${STATUS_TH[o.status]?.cls ?? 'chip-neutral'}`}>
                    {STATUS_TH[o.status]?.label ?? o.status}
                  </span>
                </p>
                {o.detail_th && <p className="mt-1 text-sm text-pencil">{o.detail_th}</p>}
                {o.status === 'rewritten' && o.result_statement_th && (
                  <p className="record mt-1 text-sm">
                    {o.result_plo_id && o.result_plo_id !== o.plo_id ? `${o.result_plo_id}: ` : ''}
                    {o.result_statement_th}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="notice notice-error mt-3">{error}</p>}

      {loadError ? (
        <p className="notice notice-warn mt-3">โหลดรายการ PLO ไม่สำเร็จ</p>
      ) : plos === null ? (
        <p className="mt-3 text-sm text-pencil">กำลังโหลด…</p>
      ) : plos.length === 0 ? (
        <p className="mt-3 text-sm text-pencil">ยังไม่มี PLO</p>
      ) : (
        <ul className="mt-3 divide-y divide-hair rounded-[4px] border border-hair">
          {plos.map((p) => {
            const on = p.plo_id in picked
            const inputId = `send-back-reason-${p.plo_id}`
            return (
              <li key={p.plo_id} className="px-4 py-3">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                      <span className="data font-semibold text-graphite">{p.plo_id}</span>
                      {p.designer_sent_back_at && (
                        <span className="chip chip-marker" title={p.designer_send_back_reason_th ?? undefined}>
                          ส่งกลับโดยผู้ออกแบบ
                        </span>
                      )}
                    </p>
                    <p className="record mt-1 text-base">{p.statement_th}</p>
                    {p.designer_sent_back_at && p.designer_send_back_reason_th && (
                      <p className="mt-1 text-sm text-marker-ink">
                        เหตุผลที่ส่งกลับ: {p.designer_send_back_reason_th}
                      </p>
                    )}
                  </div>
                  <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm text-graphite">
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={busy}
                      onChange={(e) => toggle(p.plo_id, e.target.checked)}
                    />
                    ส่งกลับ
                  </label>
                </div>
                {on && (
                  <div className="mt-2">
                    <label htmlFor={inputId} className="field-label">
                      เหตุผลที่ส่งกลับ
                    </label>
                    <textarea
                      id={inputId}
                      rows={2}
                      value={picked[p.plo_id]}
                      disabled={busy}
                      onChange={(e) => setPicked((prev) => ({ ...prev, [p.plo_id]: e.target.value }))}
                      placeholder="เช่น ควรเน้นการลงมือทำจริงมากกว่าการอธิบาย"
                      className="input resize-none"
                    />
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button onClick={send} disabled={!canSend} className="btn btn-primary">
          ส่งกลับให้ AI แก้ ({ticked.length} ข้อ)
        </button>
        {blank && <span className="text-xs text-pencil">ข้อที่เลือกต้องมีเหตุผลทุกข้อ</span>}
      </div>
    </section>
  )
}
