import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useProgram } from '../hooks/useProgram'

interface ProgramSummary {
  program_id: string
  name_th: string
  name_en: string
  degree_level: string
  created_at: string
  current_stage: string | null
  session_status: string | null
}

const STAGE_ROUTES: Record<string, string> = {
  intake: '/intake',
  stakeholder_needs: '/stakeholder-needs',
  skill_extraction: '/skill-extraction',
  plo_synthesis: '/plo-synthesis',
  plo_report: '/plo-report',
}

const STAGE_LABELS: Record<string, string> = {
  intake: 'ขั้นที่ 1: ข้อมูลหลักสูตร',
  stakeholder_needs: 'ขั้นที่ 2: ความต้องการผู้มีส่วนได้ส่วนเสีย',
  skill_extraction: 'ขั้นที่ 3: สกัดทักษะ',
  plo_synthesis: 'ขั้นที่ 4: สังเคราะห์ PLO',
  plo_report: 'ขั้นที่ 5: รายงาน PLO',
}

const DEGREE_LABELS: Record<string, string> = {
  bachelor: 'ปริญญาตรี',
  master: 'ปริญญาโท',
  doctoral: 'ปริญญาเอก',
}

const STATUS_LABELS: Record<string, string> = {
  running: 'กำลังทำงาน',
  suspended: 'รอตรวจสอบ',
  completed: 'เสร็จสิ้น',
  rejected: 'ถูกปฏิเสธ',
  failed: 'ล้มเหลว',
}

function stageRoute(stage: string | null): string {
  if (!stage) return '/intake'
  return STAGE_ROUTES[stage] ?? '/pipeline'
}

export default function Programs() {
  const [programs, setPrograms] = useState<ProgramSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
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

  const handleDelete = async (e: React.MouseEvent, p: ProgramSummary) => {
    e.stopPropagation()
    if (!window.confirm(`ลบหลักสูตร "${p.name_th}" ทั้งหมด? ข้อมูลจะหายถาวรและกู้คืนไม่ได้`)) {
      return
    }
    try {
      await api.delete(`/programs/${p.program_id}`)
      await load()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail ?? 'ลบหลักสูตรไม่สำเร็จ')
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
            {programs.map((p) => (
              <tr
                key={p.program_id}
                onClick={() => openProgram(p)}
                className="border-b cursor-pointer hover:bg-gray-50"
              >
                <td className="py-2 pr-4">
                  <div className="font-medium">{p.name_th}</div>
                  <div className="text-xs text-gray-400">
                    {p.name_en} · {p.program_id}
                  </div>
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
                      {STATUS_LABELS[p.session_status] ?? p.session_status}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4">
                  <button
                    onClick={(e) => handleDelete(e, p)}
                    className="text-red-600 hover:underline text-xs"
                  >
                    ลบ
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
