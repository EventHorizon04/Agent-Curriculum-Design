import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { CREATING_INTAKE } from '../constants/intakeMode'
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
  /** The program this one was copied from — set only by POST /{id}/copy. Not a
   *  foreign key: the source may since have been deleted, so it is shown as
   *  the id it is, never looked up. */
  copied_from: string | null
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
  const [copyingId, setCopyingId] = useState<string | null>(null)
  // A failed copy is reported on the row it was asked of, not at the top of a
  // list that may be long; a successful one marks the row it produced.
  const [copyError, setCopyError] = useState<{ id: string; message: string } | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const { programId, setProgramId } = useProgram()
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
      // The selection outlives the program otherwise: the id sits in
      // localStorage, every page reads it, and the next one opened would load a
      // curriculum the API no longer has.
      if (p.program_id === programId) setProgramId('')
      setPendingId(null)
      await load()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail ?? 'ลบหลักสูตรไม่สำเร็จ')
    } finally {
      setDeletingId(null)
    }
  }

  /** A copy is a snapshot for comparing runs: the next synthesis on either
   *  program leaves the other untouched. It is not selected, because the
   *  designer copying a program usually means to keep working on the one they
   *  had — the new row is marked instead, with a way to open it. */
  const copyProgram = async (p: ProgramSummary) => {
    setCopyingId(p.program_id)
    setCopyError(null)
    setCopiedId(null)
    try {
      const res = await api.post<{ program_id: string }>(`/programs/${p.program_id}/copy`)
      await load()
      setCopiedId(res.data.program_id)
    } catch (err: unknown) {
      // The 409s carry Thai detail meant to be shown as-is (synthesis in
      // flight, id retries exhausted).
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setCopyError({
        id: p.program_id,
        message: axiosErr.response?.data?.detail ?? 'คัดลอกหลักสูตรไม่สำเร็จ',
      })
    } finally {
      setCopyingId(null)
    }
  }

  const copied = copiedId ? programs.find((p) => p.program_id === copiedId) : undefined

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">ทะเบียนหลักสูตร</p>
          <h1 className="page-title">หลักสูตรทั้งหมด</h1>
        </div>
        <button
          // Intake is a form for *one* program and enters edit mode whenever a
          // program is selected — and one always is, since useProgram keeps it
          // in localStorage. Navigating bare therefore opened this button on a
          // form prefilled with the current curriculum, whose submit was a PUT
          // over it. The route state is what says "this is a create", which the
          // URL alone cannot: /intake is both screens.
          onClick={() => navigate('/intake', { state: CREATING_INTAKE })}
          className="btn btn-primary"
        >
          + สร้างหลักสูตรใหม่
        </button>
      </div>

      {loading && <p className="text-sm text-pencil">กำลังโหลด...</p>}

      {error && (
        <div className="notice notice-error">
          {error}{' '}
          <button onClick={load} className="font-medium underline underline-offset-2">
            ลองใหม่
          </button>
        </div>
      )}

      {!loading && !error && programs.length === 0 && (
        <div className="panel border-dashed px-6 py-10 text-center">
          <p className="font-display text-lg text-graphite">ยังไม่มีหลักสูตร</p>
          <p className="mt-1 text-sm text-pencil">
            กด “สร้างหลักสูตรใหม่” เพื่อกรอกมหาวิทยาลัย คณะ และสาขาวิชา
          </p>
        </div>
      )}

      {copied && (
        <div className="notice notice-info mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <span>
            คัดลอก <span className="data">{copied.copied_from}</span> เป็น{' '}
            <span className="data font-semibold">{copied.program_id}</span> แล้ว — หลักฐาน ทักษะ
            Need และ PLO ไปด้วยทั้งหมด ประวัติการรันไม่ได้คัดลอก
          </span>
          <button
            type="button"
            onClick={() => openProgram(copied)}
            className="font-medium underline underline-offset-2"
          >
            เปิดสำเนา →
          </button>
        </div>
      )}

      {!loading && !error && programs.length > 0 && (
        <div className="panel overflow-x-auto">
        <table className="table min-w-[40rem]">
          <thead>
            <tr>
              <th>หลักสูตร</th>
              <th>ระดับ</th>
              <th>วันที่สร้าง</th>
              <th>ขั้นที่ถึง</th>
              <th>
                <span className="sr-only">การจัดการ</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {/* The row itself is no longer the click target. Opening a program
                and deleting it were two handlers on the same event path, with
                the destructive one relying on stopPropagation to win — and a
                row is not reachable by keyboard either. The name is a real
                button; delete is its sibling, not its descendant. */}
            {programs.map((p) => (
              <tr
                key={p.program_id}
                className={[
                  'transition-colors hover:bg-sunk',
                  // The shell's program bar is hidden on this page, so this row
                  // is the only thing saying which curriculum the stage pages
                  // will open on.
                  p.program_id === programId ? 'bg-stamp-wash/60 hover:bg-stamp-wash' : '',
                  p.program_id === copiedId ? 'bg-marker-wash/70 hover:bg-marker-wash' : '',
                ].join(' ')}
              >
                <td>
                  <button
                    type="button"
                    onClick={() => openProgram(p)}
                    className="w-full text-left"
                  >
                    <span className="flex flex-wrap items-center gap-2 font-medium text-graphite hover:text-stamp hover:underline hover:underline-offset-2">
                      {programLabel(p)}
                      {p.program_id === programId && (
                        <span className="chip chip-stamp">เลือกอยู่</span>
                      )}
                      {p.program_id === copiedId && (
                        <span className="chip chip-marker">เพิ่งคัดลอก</span>
                      )}
                    </span>
                    <span className="data block text-xs text-lead">
                      {[p.faculty, p.name_en].filter(Boolean).join(' · ')}
                      {(p.faculty || p.name_en) && ' · '}
                      {p.program_id}
                    </span>
                    {p.copied_from && (
                      <span className="block text-xs text-pencil">
                        สำเนาของ <span className="data">{p.copied_from}</span>
                      </span>
                    )}
                  </button>
                </td>
                <td className="whitespace-nowrap">{DEGREE_LABELS[p.degree_level] ?? p.degree_level}</td>
                <td className="data whitespace-nowrap text-pencil">
                  {new Date(p.created_at).toLocaleDateString('th-TH', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </td>
                <td>
                  <span className="chip chip-neutral">
                    {p.current_stage
                      ? (STAGE_LABELS[p.current_stage] ?? p.current_stage)
                      : 'ยังไม่เริ่ม'}
                  </span>
                  {p.session_status && (
                    <span className="ml-2 text-xs text-pencil">
                      {SESSION_STATUS_LABELS[p.session_status] ?? p.session_status}
                    </span>
                  )}
                </td>
                <td className="text-right whitespace-nowrap">
                  {pendingId === p.program_id ? (
                    <span className="inline-flex items-center gap-2">
                      <span className="text-xs text-mandate">ลบถาวร กู้คืนไม่ได้</span>
                      <button
                        type="button"
                        onClick={() => confirmDelete(p)}
                        disabled={deletingId === p.program_id}
                        className="btn btn-sm btn-danger"
                      >
                        {deletingId === p.program_id ? 'กำลังลบ...' : 'ยืนยันลบ'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setPendingId(null)}
                        disabled={deletingId === p.program_id}
                        className="btn btn-sm btn-secondary"
                      >
                        ยกเลิก
                      </button>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => copyProgram(p)}
                        disabled={copyingId !== null}
                        title="คัดลอกหลักสูตรนี้พร้อมหลักฐาน ทักษะ Need และ PLO — ใช้เก็บผลรอบนี้ไว้เทียบกับรอบถัดไป"
                        className="btn btn-sm btn-quiet"
                      >
                        {copyingId === p.program_id ? 'กำลังคัดลอก...' : 'คัดลอก'}
                      </button>
                      {/* Padded on purpose: the hit area used to be the two
                          glyphs of the label and nothing more. */}
                      <button
                        type="button"
                        onClick={() => setPendingId(p.program_id)}
                        className="btn btn-sm btn-danger-quiet"
                      >
                        ลบ
                      </button>
                    </span>
                  )}
                  {copyError?.id === p.program_id && (
                    <p className="mt-1 max-w-xs text-left text-xs whitespace-normal text-mandate" role="alert">
                      {copyError.message}
                    </p>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  )
}
