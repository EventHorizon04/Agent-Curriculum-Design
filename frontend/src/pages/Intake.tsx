import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useProgram } from '../hooks/useProgram'

const DEGREE_OPTIONS = [
  { value: 'bachelor', label: 'ปริญญาตรี' },
  { value: 'master',   label: 'ปริญญาโท' },
  { value: 'doctoral', label: 'ปริญญาเอก' },
]

interface FormState {
  name_th: string
  name_en: string
  field: string
  isced_code: string
  degree_level: string
  duration_years: number
  faculty: string
  university: string
  objectives_raw: string
  goals_raw: string
}

const INITIAL: FormState = {
  name_th: '', name_en: '', field: '', isced_code: '',
  degree_level: 'bachelor', duration_years: 4,
  faculty: '', university: '',
  objectives_raw: '', goals_raw: '',
}

export default function Intake() {
  const navigate = useNavigate()
  const { programId, setProgramId } = useProgram()
  const [form, setForm] = useState<FormState>(INITIAL)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  function handleChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) {
    const { name, value } = e.target
    setForm(prev => ({ ...prev, [name]: value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')

    const required: (keyof FormState)[] = [
      'name_th', 'name_en', 'field',
      'faculty', 'university', 'objectives_raw', 'goals_raw',
    ]
    if (required.some(k => !String(form[k]).trim())) {
      setError('กรุณากรอกข้อมูลที่มีเครื่องหมาย * ให้ครบถ้วน')
      return
    }

    const objectives = form.objectives_raw
      .split('\n')
      .map(l => l.trim())
      .filter(Boolean)

    const goals = form.goals_raw
      .split('\n')
      .map(l => l.trim())
      .filter(Boolean)

    setLoading(true)
    try {
      const resp = await api.post('/programs/', {
        name_th: form.name_th,
        name_en: form.name_en,
        field: form.field,
        isced_code: form.isced_code.trim() || null,
        degree_level: form.degree_level,
        duration_years: Number(form.duration_years),
        faculty: form.faculty,
        university: form.university,
        program_objectives_th: objectives,
        program_goals_th: goals,
      })
      const newId = resp.data.program_id
      setProgramId(newId)
      setSuccess(`บันทึกหลักสูตร "${form.name_th}" สำเร็จ (รหัส: ${newId})`)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status: number; data: unknown } }
      if (axiosErr.response) {
        setError(`API error ${axiosErr.response.status}: ${JSON.stringify(axiosErr.response.data)}`)
      } else {
        setError('เชื่อมต่อ API ไม่ได้ — ตรวจสอบว่า backend รันอยู่ (./scripts/start-dev.ps1)')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto text-left">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-800">ขั้นตอนที่ 1 — ข้อมูลหลักสูตร</h1>
        <p className="text-gray-500 text-sm mt-1">
          กรอกข้อมูลพื้นฐานของหลักสูตรเพื่อเริ่มกระบวนการออกแบบ OBE
        </p>
        <p className="mt-1 text-xs text-gray-500">
          วิสัยทัศน์ พันธกิจ และอัตลักษณ์ ให้บันทึกเป็นหลักฐานที่หน้า Stakeholder Needs
          (ประเภท "วิสัยทัศน์/พันธกิจ/อัตลักษณ์")
        </p>
        {programId && (
          <div className="mt-2 inline-flex items-center gap-2 bg-blue-50 border border-blue-100 text-blue-700 text-xs font-medium px-3 py-1 rounded-full">
            <span className="w-1.5 h-1.5 bg-blue-500 rounded-full"></span>
            หลักสูตรปัจจุบัน: {programId}
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 mb-4 text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 mb-4 text-sm flex items-center justify-between">
          <span>✓ {success}</span>
          <button
            onClick={() => navigate('/stakeholder-needs')}
            className="underline font-medium hover:text-green-900 ml-4"
          >
            ไปที่หน้าหลักฐาน →
          </button>
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <Field label="ชื่อหลักสูตร (ภาษาไทย) *" name="name_th" value={form.name_th} onChange={handleChange} />
          <Field label="ชื่อหลักสูตร (ภาษาอังกฤษ) *" name="name_en" value={form.name_en} onChange={handleChange} />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Field label="สาขาวิชา *" name="field" value={form.field} onChange={handleChange} placeholder="Computer Science" />
          <Field label="รหัส ISCED-F" name="isced_code" value={form.isced_code} onChange={handleChange} placeholder="0613" />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">ระดับปริญญา</label>
            <select
              name="degree_level"
              value={form.degree_level}
              onChange={handleChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {DEGREE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">จำนวนปีการศึกษา</label>
            <input
              type="number" name="duration_years" min={1} max={8}
              value={form.duration_years} onChange={handleChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <Field label="มหาวิทยาลัย *" name="university" value={form.university} onChange={handleChange} />
        </div>

        <Field label="คณะ *" name="faculty" value={form.faculty} onChange={handleChange} />

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            วัตถุประสงค์หลักสูตร *{' '}
            <span className="text-gray-400 font-normal">(แต่ละรายการ 1 บรรทัด)</span>
          </label>
          <textarea
            name="objectives_raw" rows={4} value={form.objectives_raw} onChange={handleChange}
            placeholder={"1. ผลิตบัณฑิตที่มีความรู้...\n2. พัฒนาทักษะด้าน..."}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            เป้าหมายหลักสูตร *{' '}
            <span className="text-gray-400 font-normal">(แต่ละรายการ 1 บรรทัด)</span>
          </label>
          <textarea
            name="goals_raw" rows={4} value={form.goals_raw} onChange={handleChange}
            placeholder={"1. ผลิตบัณฑิตที่ตอบสนองความต้องการ...\n2. ส่งเสริมการเรียนรู้ตลอดชีวิต..."}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        <button
          type="submit" disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium rounded-lg py-2.5 text-sm transition-colors cursor-pointer disabled:cursor-not-allowed"
        >
          {loading ? 'กำลังบันทึก...' : 'บันทึกและเริ่มกระบวนการ'}
        </button>
      </form>
    </div>
  )
}

function Field({
  label, name, value, onChange, placeholder,
}: {
  label: string
  name: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  placeholder?: string
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input
        type="text" name={name} value={value} onChange={onChange} placeholder={placeholder}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  )
}
