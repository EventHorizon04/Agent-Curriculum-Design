import { useEffect, useRef, useState } from 'react'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'

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

const STAGE_ORDER = [
  { key: 'intake', label: 'Intake' },
  { key: 'stakeholder_needs', label: 'Stakeholder' },
  { key: 'skill_extraction', label: 'Skills' },
  { key: 'plo_synthesis', label: 'PLOs' },
  { key: 'plo_report', label: 'PLO Report' },
]

const STAGE_PATHS: Record<string, string> = {
  intake: '/',
  stakeholder_needs: '/stakeholder-needs',
  skill_extraction: '/skill-extraction',
  plo_synthesis: '/plo-synthesis',
  plo_report: '/plo-report',
}

const STATUS_COLOR: Record<SessionStatus, string> = {
  running: '#2563eb',
  suspended: '#d97706',
  completed: '#16a34a',
  rejected: '#dc2626',
  failed: '#9333ea',
}

function stageIcon(
  stageKey: string,
  session: Session,
): { icon: string; color: string; clickable: boolean } {
  const currentIdx = STAGE_ORDER.findIndex((s) => s.key === session.current_stage)
  const thisIdx = STAGE_ORDER.findIndex((s) => s.key === stageKey)

  if (session.status === 'rejected' && stageKey === session.current_stage)
    return { icon: '✗', color: '#dc2626', clickable: false }
  if (stageKey === session.current_stage && session.status === 'suspended')
    return { icon: '⏸', color: '#d97706', clickable: false }
  if (stageKey === session.current_stage && session.status === 'running')
    return { icon: '▶', color: '#2563eb', clickable: false }
  if (session.status === 'completed' || thisIdx < currentIdx)
    return { icon: '✓', color: '#16a34a', clickable: true }
  return { icon: '·', color: '#9ca3af', clickable: false }
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
      setError(axiosErr.response?.data?.detail ?? 'ลบ session ไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: 12,
        padding: 16,
        marginBottom: 12,
        background: '#fff',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontWeight: 600, fontSize: 13 }}>
            Session {session.session_id.slice(0, 8)}
          </span>
          <span style={{ marginLeft: 8, fontSize: 12, color: '#6b7280' }}>
            {new Date(session.created_at).toLocaleString('th-TH')}
          </span>
        </div>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: STATUS_COLOR[session.status],
            background: STATUS_COLOR[session.status] + '18',
            borderRadius: 6,
            padding: '2px 8px',
          }}
        >
          {session.status.toUpperCase()}
        </span>
      </div>

      {/* The same column carries a suspension's review prompt and a failed
          run's reason — a stage refusing to run for want of evidence, skills or
          Needs. A failed session used to show a bare FAILED with the reason only
          in the server log, while the same precondition hit from a stage page
          answers with it in Thai. */}
      {session.suspended_message && session.status === 'suspended' && (
        <p style={{ margin: '8px 0 4px', fontSize: 12, color: '#92400e' }}>
          ⏸ {session.suspended_message}
        </p>
      )}

      {session.suspended_message && session.status === 'failed' && (
        <p style={{ margin: '8px 0 4px', fontSize: 12, color: '#b91c1c' }}>
          ✕ {session.suspended_message}
        </p>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 10 }}>
        {STAGE_ORDER.map((stage, i) => {
          const { icon, color, clickable } = stageIcon(stage.key, session)
          return [
            <span
              key={stage.key}
              title={stage.label}
              style={{
                fontSize: 13,
                color,
                fontWeight: 600,
                cursor: clickable ? 'pointer' : 'default',
                textDecoration: clickable ? 'underline' : 'none',
              }}
              onClick={() => {
                if (clickable) window.location.href = STAGE_PATHS[stage.key]
              }}
            >
              {icon} {stage.label}
            </span>,
            i < STAGE_ORDER.length - 1 && (
              <span key={`arrow-${stage.key}`} style={{ color: '#d1d5db' }}>
                →
              </span>
            ),
          ]
        })}
      </div>

      {session.status === 'suspended' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button
            onClick={() => doAction('approve')}
            disabled={loading}
            style={{
              padding: '6px 16px',
              background: '#16a34a',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            Approve
          </button>
          <button
            onClick={() => doAction('reject')}
            disabled={loading}
            style={{
              padding: '6px 16px',
              background: '#dc2626',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            Reject
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
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 12,
            paddingTop: 10,
            borderTop: '1px solid #f3f4f6',
          }}
        >
          {error && <span style={{ fontSize: 12, color: '#b91c1c' }}>{error}</span>}
          {confirmingDelete ? (
            <>
              <span style={{ fontSize: 12, color: '#6b7280' }}>
                ลบประวัติการรันนี้ถาวร รวมถึง checkpoint ที่ค้างอยู่ — กู้คืนไม่ได้
              </span>
              <button
                onClick={doDelete}
                disabled={loading}
                style={{
                  marginLeft: 'auto',
                  padding: '4px 12px',
                  background: '#dc2626',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: 12,
                }}
              >
                {loading ? 'กำลังลบ...' : 'ยืนยันลบ'}
              </button>
              <button
                onClick={() => setConfirmingDelete(false)}
                disabled={loading}
                style={{
                  padding: '4px 12px',
                  background: 'transparent',
                  color: '#6b7280',
                  border: '1px solid #e5e7eb',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                ยกเลิก
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmingDelete(true)}
              style={{
                marginLeft: 'auto',
                padding: '4px 10px',
                background: 'transparent',
                color: '#9ca3af',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 12,
              }}
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

  useEffect(() => {
    fetchSessions()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [programId])

  async function handleNewRun() {
    if (!programId) return alert('กรุณา intake โปรแกรมก่อน')
    setStarting(true)
    try {
      await api.post(`/programs/${programId}/sessions/`)
      await fetchSessions()
      startPolling()
    } catch {
      // Swallow: matches the prior fetch()-based behaviour, which skipped
      // the refresh/poll on a non-ok response and fell straight to `finally`.
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>Pipeline Runs</h2>
        <button
          onClick={handleNewRun}
          disabled={starting || !programId}
          style={{
            padding: '8px 18px',
            background: '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: 13,
          }}
        >
          {starting ? 'Starting…' : '+ New Run'}
        </button>
      </div>

      {!programId && (
        <p style={{ color: '#dc2626', fontSize: 13 }}>ยังไม่มี program — ไปที่ Intake ก่อน</p>
      )}

      {sessions.length === 0 && programId && (
        <p style={{ color: '#6b7280', fontSize: 13 }}>ยังไม่มี session — กด + New Run</p>
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
