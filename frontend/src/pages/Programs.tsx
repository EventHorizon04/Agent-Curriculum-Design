import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useProgram } from '../hooks/useProgram'
import { SESSION_STATUS_LABELS, STAGE_LABELS, STAGE_ROUTES } from '../constants/stages'

interface ProgramSummary {
  program_id: string
  name_th: string
  name_en: string
  field: string
  faculty: string
  degree_level: string
  created_at: string
  current_stage: string | null
  session_status: string | null
}

/** Programs created before intake dropped the name field still have one; the
 *  rest are identified by their field of study. */
function programLabel(p: ProgramSummary): string {
  return p.name_th || p.field || p.program_id
}

const DEGREE_LABELS: Record<string, string> = {
  bachelor: 'ปริญญาตรี',
  master: 'ปริญญาโท',
  doctoral: 'ปริญญาเอก',
}

function stageRoute(stage: string | null): string {
  if (!stage) return '/intake'
  return STAGE_ROUTES[stage] ?? '/pipeline'
}

export default function Programs() {
  const [programs, setPrograms] = useState<ProgramSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Which row is asking for confirmation, and which one is mid-request. Both are
  // ids rather than booleans so a second row cannot inherit the first row's
  // pending state when the list re-renders.
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const { setProgramId } = useProgram()
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<ProgramSummary[]>('/programs/')
      setPrograms(res.data)
    } catch {
      setError('โหลดรายการหลักสูตรไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const openProgram = (p: ProgramSummary) => {
    setProgramId(p.program_id)
    navigate(stageRoute(p.current_stage))
  }

  /** Deletion confirms in the page, not through `window.confirm`.
   *
   *  The native dialog returns `false` for "the user cancelled" and for "no
   *  dialog was ever shown" alike — a browser that suppresses dialogs turns a
   *  permanently destructive action into a button that silently does nothing,
   *  with no error to show. An inline confirmation is state we can see. */
  const confirmDelete = async (p: ProgramSummary) => {
    setDeletingId(p.program_id)
    setError(null)
    try {
      await api.delete(`/programs/${p.program_id}`)
      setPendingId(null)
      await load()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail ?? 'ลบหลักสูตรไม่สำเร็จ')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">หลักสูตรทั้งหมด</h1>
        <button
          onClick={() => navigate('/intake')}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700"
        >
          + สร้างหลักสูตรใหม่
        </button>
      </div>

      {loading && <p className="text-gray-500 text-sm">กำลังโหลด...</p>}

      {error && (
        <div className="text-sm text-red-600">
          {error}{' '}
          <button onClick={load} className="underline">
            ลองใหม่
          </button>
        </div>
      )}

      {!loading && !error && programs.length === 0 && (
        <p className="text-gray-500 text-sm">ยังไม่มีหลักสูตร — เริ่มสร้างหลักสูตรแรกได้เลย</p>
      )}

      {!loading && !error && programs.length > 0 && (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-left border-b text-gray-500">
              <th className="py-2 pr-4">ชื่อหลักสูตร</th>
              <th className="py-2 pr-4">ระดับ</th>
              <th className="py-2 pr-4">วันที่สร้าง</th>
              <th className="py-2 pr-4">สถานะ</th>
              <th className="py-2 pr-4"></th>
            </tr>
          </thead>
          <tbody>
            {/* The row itself is no longer the click target. Opening a program
                and deleting it were two handlers on the same event path, with
                the destructive one relying on stopPropagation to win — and a
                row is not reachable by keyboard either. The name is a real
                button; delete is its sibling, not its descendant. */}
            {programs.map((p) => (
              <tr key={p.program_id} className="border-b hover:bg-gray-50">
                <td className="py-2 pr-4">
                  <button
                    type="button"
                    onClick={() => openProgram(p)}
                    className="w-full text-left"
                  >
                    <span className="block font-medium hover:underline">{programLabel(p)}</span>
                    <span className="block text-xs text-gray-400">
                      {[p.faculty, p.name_en].filter(Boolean).join(' · ')}
                      {(p.faculty || p.name_en) && ' · '}
                      {p.program_id}
                    </span>
                  </button>
                </td>
                <td className="py-2 pr-4">{DEGREE_LABELS[p.degree_level] ?? p.degree_level}</td>
                <td className="py-2 pr-4">
                  {new Date(p.created_at).toLocaleDateString('th-TH', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </td>
                <td className="py-2 pr-4">
                  <span className="inline-block bg-gray-100 rounded px-2 py-0.5 text-xs">
                    {p.current_stage
                      ? (STAGE_LABELS[p.current_stage] ?? p.current_stage)
                      : 'ยังไม่เริ่ม'}
                  </span>
                  {p.session_status && (
                    <span className="ml-2 text-xs text-gray-400">
                      {SESSION_STATUS_LABELS[p.session_status] ?? p.session_status}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4 text-right whitespace-nowrap">
                  {pendingId === p.program_id ? (
                    <span className="inline-flex items-center gap-2">
                      <span className="text-xs text-gray-500">ลบถาวร กู้คืนไม่ได้</span>
                      <button
                        type="button"
                        onClick={() => confirmDelete(p)}
                        disabled={deletingId === p.program_id}
                        className="rounded bg-red-600 px-2 py-1 text-xs text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        {deletingId === p.program_id ? 'กำลังลบ...' : 'ยืนยันลบ'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setPendingId(null)}
                        disabled={deletingId === p.program_id}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                      >
                        ยกเลิก
                      </button>
                    </span>
                  ) : (
                    /* Padded on purpose: the hit area used to be the two glyphs
                       of the label and nothing more. */
                    <button
                      type="button"
                      onClick={() => setPendingId(p.program_id)}
                      className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50 hover:underline"
                    >
                      ลบ
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
