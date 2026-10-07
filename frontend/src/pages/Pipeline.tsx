import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'
import { SESSION_STATUS_LABELS, STAGES } from '../constants/stages'

type SessionStatus = 'running' | 'suspended' | 'completed' | 'rejected' | 'failed'

interface Session {
  session_id: string
  program_id: string
  thread_id: string
  status: SessionStatus
  current_stage: string | null
  suspended_message: string | null
  created_at: string
  updated_at: string
}

/** The graph's interrupt messages are English and fixed (graph.py), and each
 *  one belongs to exactly one checkpoint — so the page says it in Thai from the
 *  stage the session stopped at, and keeps the original for anything it does
 *  not recognise. */
const CHECKPOINT_TH: Record<string, string> = {
  stakeholder_needs: 'รวบรวมหลักฐานเสร็จแล้ว — ตรวจการจำแนกหลักฐานก่อนสกัดทักษะ',
  skill_extraction: 'สกัดทักษะและรวม Need เสร็จแล้ว — ตรวจทักษะและ Need ก่อนสังเคราะห์ PLO',
  plo_synthesis: 'สังเคราะห์ PLO เสร็จแล้ว — ตรวจและแก้ PLO ก่อนสร้างรายงาน',
  plo_report: 'สร้างรายงาน PLO เสร็จแล้ว — ตรวจรายงานก่อนส่งออก',
}

// A finished, rejected or failed run is a terminal state a person (or the run)
// produced and reads as a stamp; a run waiting on the designer is the pending
// stamp; a run still in flight is only a label.
const STATUS_CLASS: Record<SessionStatus, string> = {
  running: 'chip chip-neutral',
  suspended: 'stamp stamp-pending',
  completed: 'stamp',
  rejected: 'stamp stamp-mandate',
  failed: 'stamp stamp-mandate',
}

type StepState = 'done' | 'running' | 'waiting' | 'rejected' | 'ahead'

function stepState(stageKey: string, session: Session): StepState {
  const currentIdx = STAGES.findIndex((s) => s.key === session.current_stage)
  const thisIdx = STAGES.findIndex((s) => s.key === stageKey)

  if (session.status === 'rejected' && stageKey === session.current_stage) return 'rejected'
  if (stageKey === session.current_stage && session.status === 'suspended') return 'waiting'
  if (stageKey === session.current_stage && session.status === 'running') return 'running'
  if (session.status === 'completed' || thisIdx < currentIdx) return 'done'
  return 'ahead'
}

const STEP_TITLE: Record<StepState, string> = {
  done: 'ผ่านแล้ว',
  running: 'กำลังทำงาน',
  waiting: 'รอตรวจสอบ',
  rejected: 'ถูกปฏิเสธที่ขั้นนี้',
  ahead: 'ยังไม่ถึง',
}

/** Same marks as the rail — ● done, ◐ waiting on the designer, ○ not reached —
 *  plus the moving dial for the stage that is running right now. */
function StepMark({ state }: { state: StepState }) {
  if (state === 'running') return <span className="run-dial h-3 w-3" aria-hidden="true" />
  if (state === 'rejected')
    return <span className="map-mark border-mandate bg-mandate" aria-hidden="true" />
  const variant = state === 'done' ? 'passed' : state === 'waiting' ? 'current' : 'ahead'
  return <span className={`map-mark map-mark-${variant}`} aria-hidden="true" />
}

function SessionCard({
  session,
  programId,
  onAction,
}: {
  session: Session
  programId: string
  onAction: () => void
}) {
  const [loading, setLoading] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [error, setError] = useState('')
  const reviewRoute = STAGES.find((s) => s.key === session.current_stage)?.route

  async function doAction(action: 'approve' | 'reject') {
    setLoading(true)
    try {
      await api.post(`/programs/${programId}/sessions/${session.session_id}/${action}`)
    } catch {
      // Swallow: matches the prior fetch()-based behaviour, which never
      // checked res.ok here either. onAction() below re-polls regardless.
    }
    setLoading(false)
    onAction()
  }

  /** Remove this run from the history, checkpoint and all.
   *
   *  Unlike approve/reject the failure is shown rather than swallowed: the API
   *  refuses a running session, and a delete that silently did nothing would
   *  read as one that worked until the row reappeared on the next poll.
   */
  async function doDelete() {
    setLoading(true)
    setError('')
    try {
      await api.delete(`/programs/${programId}/sessions/${session.session_id}`)
      setConfirmingDelete(false)
      onAction()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail ?? 'ลบประวัติการรันไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="panel mb-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <span className="text-sm font-semibold text-graphite">
            การรัน <span className="data">{session.session_id.slice(0, 8)}</span>
          </span>
          <span className="data ml-2 text-xs text-pencil">
            {new Date(session.created_at).toLocaleString('th-TH')}
          </span>
        </div>
        <span className={STATUS_CLASS[session.status]}>
          {SESSION_STATUS_LABELS[session.status] ?? session.status}
        </span>
      </div>

      {/* The same column carries a suspension's review prompt and a failed
          run's reason — a stage refusing to run for want of evidence, skills or
          Needs. A failed session used to show a bare FAILED with the reason only
          in the server log, while the same precondition hit from a stage page
          answers with it in Thai. */}
      {session.suspended_message && session.status === 'suspended' && (
        <div className="notice notice-warn mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <span title={session.suspended_message}>
            {(session.current_stage && CHECKPOINT_TH[session.current_stage]) ||
              session.suspended_message}
          </span>
          {reviewRoute && (
            <Link to={reviewRoute} className="font-medium underline underline-offset-2">
              ไปตรวจที่หน้านี้ →
            </Link>
          )}
        </div>
      )}

      {session.suspended_message && session.status === 'failed' && (
        <p className="notice notice-error mt-3">{session.suspended_message}</p>
      )}

      {/* Stages already passed are links to their page; the rest are not,
          because there is nothing there to review yet. */}
      <ol className="mt-4 flex flex-wrap items-center gap-x-1 gap-y-2">
        {STAGES.map((stage, i) => {
          const state = stepState(stage.key, session)
          const body = (
            <>
              <StepMark state={state} />
              <span className="data text-[0.6875rem] text-lead">{stage.ordinal}</span>
              <span>{stage.label}</span>
              <span className="sr-only"> — {STEP_TITLE[state]}</span>
            </>
          )
          const tone =
            state === 'rejected'
              ? 'text-mandate'
              : state === 'ahead'
                ? 'text-lead'
                : 'text-graphite'
          const pill = 'flex items-center gap-1.5 rounded-[3px] px-1.5 py-0.5 text-[0.8125rem] whitespace-nowrap'
          return (
            <li key={stage.key} className="flex items-center gap-1">
              {state === 'done' ? (
                <Link
                  to={stage.route}
                  title={STEP_TITLE[state]}
                  className={`${pill} ${tone} hover:bg-sunk hover:underline hover:underline-offset-2`}
                >
                  {body}
                </Link>
              ) : (
                <span
                  title={STEP_TITLE[state]}
                  className={[
                    pill,
                    tone,
                    state === 'running' || state === 'waiting' ? 'bg-sunk font-semibold' : '',
                  ].join(' ')}
                >
                  {body}
                </span>
              )}
              {i < STAGES.length - 1 && (
                <span className="text-hair-strong" aria-hidden="true">
                  —
                </span>
              )}
            </li>
          )
        })}
      </ol>

      {session.status === 'running' && (
        <p className="mt-3 flex items-center gap-2 text-xs text-pencil" role="status">
          <span className="run-dial h-3 w-3" aria-hidden="true" />
          กำลังทำงาน — หน้านี้อัปเดตเองทุก 2 วินาที และจะหยุดรอให้ตรวจเมื่อถึง checkpoint ถัดไป
        </p>
      )}

      {session.status === 'suspended' && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => doAction('approve')}
            disabled={loading}
            className="btn btn-sm btn-primary"
          >
            อนุมัติ ไปขั้นถัดไป
          </button>
          <button
            onClick={() => doAction('reject')}
            disabled={loading}
            className="btn btn-sm btn-danger"
          >
            ปฏิเสธ หยุดการรันนี้
          </button>
        </div>
      )}

      {/* Confirmed in the card, not through `window.confirm` — a browser that
          suppresses dialogs returns the same `false` for "cancelled" as for
          "never shown", which turns a permanent delete into a button that does
          nothing with no error to show. Same reason the program list does it
          this way. A running session has no button at all: the API refuses it,
          because deleting the row does not stop the background task that is
          still writing stage output and status back. */}
      {session.status !== 'running' && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-hair pt-2.5">
          {error && <span className="text-xs text-mandate">{error}</span>}
          {confirmingDelete ? (
            <>
              <span className="text-xs text-mandate">
                ลบประวัติการรันนี้ถาวร รวมถึง checkpoint ที่ค้างอยู่ — กู้คืนไม่ได้
              </span>
              <button
                onClick={doDelete}
                disabled={loading}
                className="btn btn-sm btn-danger ml-auto"
              >
                {loading ? 'กำลังลบ...' : 'ยืนยันลบ'}
              </button>
              <button
                onClick={() => setConfirmingDelete(false)}
                disabled={loading}
                className="btn btn-sm btn-secondary"
              >
                ยกเลิก
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmingDelete(true)}
              className="btn btn-sm btn-danger-quiet ml-auto"
            >
              ลบประวัติ
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default function Pipeline() {
  const { programId } = useProgram()
  const [sessions, setSessions] = useState<Session[]>([])
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')
  // What stage 1 will read. A run with nothing to classify raises there and
  // lands as a failed session, which is a correct refusal arriving one round
  // trip too late: the page could have said so before the button was pressed.
  // Null until the count is known, so the button is not disabled while loading.
  const [evidenceCount, setEvidenceCount] = useState<number | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchSessions() {
    if (!programId) return
    try {
      const res = await api.get<Session[]>(`/programs/${programId}/sessions/`)
      setSessions(res.data)
    } catch {
      // Swallow: matches the prior fetch()-based behaviour, which left
      // `sessions` untouched on a non-ok response.
    }
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      await fetchSessions()
      setSessions((prev) => {
        const hasRunning = prev.some((s) => s.status === 'running')
        if (!hasRunning && pollRef.current) {
          clearInterval(pollRef.current)
          pollRef.current = null
        }
        return prev
      })
    }, 2000)
  }

  // A run already in flight when the page opens (started from another tab, or
  // before a reload) has to be followed too, not only one started here.
  useEffect(() => {
    if (sessions.some((s) => s.status === 'running') && !pollRef.current) startPolling()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions])

  useEffect(() => {
    fetchSessions()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [programId])

  // Read once per program rather than inside fetchSessions, which the poll
  // calls every two seconds while a run is in flight.
  useEffect(() => {
    if (!programId) {
      setEvidenceCount(null)
      return
    }
    let cancelled = false
    api
      .get<unknown[]>(`/programs/${programId}/evidence/`)
      .then((res) => {
        if (!cancelled) setEvidenceCount(res.data.length)
      })
      .catch(() => {
        // Unknown, not zero. A failed read must not block a run the API would
        // have accepted.
        if (!cancelled) setEvidenceCount(null)
      })
    return () => {
      cancelled = true
    }
  }, [programId])

  async function handleNewRun() {
    if (!programId) return
    setStarting(true)
    setStartError('')
    try {
      await api.post(`/programs/${programId}/sessions/`)
      await fetchSessions()
      startPolling()
    } catch (err: unknown) {
      // Shown, not swallowed. A start that fails outright leaves no session row
      // to carry the reason, so the page was the only place it could appear and
      // the button simply did nothing.
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setStartError(axiosErr.response?.data?.detail ?? 'เริ่มการรันไม่สำเร็จ')
    } finally {
      setStarting(false)
    }
  }

  function handleAction() {
    fetchSessions()
    startPolling()
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">ทุกขั้นต่อเนื่อง</p>
          <h1 className="page-title">รันทั้งชุด</h1>
        </div>
        <button
          onClick={handleNewRun}
          disabled={starting || !programId || evidenceCount === 0}
          title={
            evidenceCount === 0
              ? 'ยังไม่มีหลักฐาน — ขั้นแรกของ pipeline อ่านจากตาราง evidence'
              : undefined
          }
          className="btn btn-primary"
        >
          {starting ? 'กำลังเริ่ม…' : '+ เริ่มรันใหม่'}
        </button>
      </div>

      {!programId && (
        <p className="notice notice-error">
          ยังไม่ได้เลือกหลักสูตร —{' '}
          <Link to="/" className="font-medium underline underline-offset-2">
            เลือกจากรายการหลักสูตร
          </Link>
        </p>
      )}

      {/* The refusal stage 1 would raise, said before the run instead of after
          it. Same rule, same wording as the stage itself — a program with no
          evidence has nothing for the pipeline to classify. */}
      {programId && evidenceCount === 0 && (
        <p className="notice notice-warn mb-3">
          ยังไม่มีหลักฐานในหลักสูตรนี้ — pipeline ขั้นแรกอ่านจากตาราง evidence จึงยังเริ่มไม่ได้{' '}
          <Link to="/stakeholder-needs" className="link">
            ไปเพิ่มหลักฐาน
          </Link>
        </p>
      )}

      {startError && (
        <p className="notice notice-error mb-3">{startError}</p>
      )}

      {sessions.length === 0 && programId && (
        <div className="panel border-dashed px-6 py-10 text-center">
          <p className="font-display text-lg text-graphite">ยังไม่เคยรันทั้งชุด</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-pencil">
            กด “เริ่มรันใหม่” ระบบจะรันทีละขั้นและหยุดรอให้ตรวจที่ทุก checkpoint
          </p>
        </div>
      )}

      {sessions.map((s) => (
        <SessionCard
          key={s.session_id}
          session={s}
          programId={programId}
          onAction={handleAction}
        />
      ))}
    </div>
  )
}
