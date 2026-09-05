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
  university: string
  faculty: string
  field: string
  scope_th: string
  degree_level: string
  duration_years: number
}

const INITIAL: FormState = {
  university: '', faculty: '', field: '', scope_th: '',
  degree_level: 'bachelor', duration_years: 4,
}

// Shown under the scope field. Every line answers a measured result: an
// exclusion list scored worse than writing nothing at all, and so did a broad or
// vague statement, so an empty box beats a half-hearted one.
const SCOPE_HINTS = [
  'เขียนเฉพาะสิ่งที่หลักสูตรครอบคลุม แจกแจงเป็นรายการ 3-4 อย่าง',
  'อย่าเขียนรายการ "ไม่รวมถึง" — จากการทดสอบ รายการกันออกทำให้ระบบตัดสินแย่ลงกว่าไม่เขียนอะไรเลย',
  'เขียนกว้าง ๆ หรือลอย ๆ แย่กว่าไม่เขียน — ถ้ายังแจกแจงไม่ได้ ให้เว้นว่างไว้ก่อน',
]

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

    const required: (keyof FormState)[] = ['university', 'faculty', 'field']
    if (required.some(k => !String(form[k]).trim())) {
      setError('กรุณากรอกข้อมูลที่มีเครื่องหมาย * ให้ครบถ้วน')
      return
    }

    setLoading(true)
    try {
      const resp = await api.post('/programs/', {
        university: form.university,
        faculty: form.faculty,
        field: form.field,
        scope_th: form.scope_th.trim(),
        degree_level: form.degree_level,
        duration_years: Number(form.duration_years),
      })
      const newId = resp.data.program_id
      setProgramId(newId)
      setSuccess(`บันทึกหลักสูตร "${form.field}" สำเร็จ (รหัส: ${newId})`)
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
        <Field
          label="มหาวิทยาลัย / สถาบัน *"
          hint="หน่วยงานใหญ่สุด"
          name="university" value={form.university} onChange={handleChange}
          placeholder="จุฬาลงกรณ์มหาวิทยาลัย"
        />

        <Field
          label="คณะ *"
          hint="หน่วยงานหลักที่แบ่งตามศาสตร์"
          name="faculty" value={form.faculty} onChange={handleChange}
          placeholder="คณะรัฐศาสตร์"
        />

        <Field
          label="สาขาวิชา / ภาควิชา *"
          hint="แขนงวิชาเฉพาะด้าน"
          name="field" value={form.field} onChange={handleChange}
          placeholder="ความสัมพันธ์ระหว่างประเทศ"
        />

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            ขอบเขตของหลักสูตร (ไม่บังคับ)
          </label>
          <textarea
            name="scope_th" rows={3} value={form.scope_th} onChange={handleChange}
            placeholder="หลักสูตรนี้ครอบคลุม… (แจกแจง 3-4 รายการ)"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <ul className="mt-1 space-y-0.5 text-xs text-gray-500">
            {SCOPE_HINTS.map(hint => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        </div>

        <hr className="border-gray-100" />

        <div className="grid grid-cols-2 gap-4">
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
  label, name, value, onChange, placeholder, hint,
}: {
  label: string
  name: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  placeholder?: string
  hint?: string
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {hint && <span className="text-gray-400 font-normal ml-2">— {hint}</span>}
      </label>
      <input
        type="text" name={name} value={value} onChange={onChange} placeholder={placeholder}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  )
}
