import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
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

/** What Programs' "+ สร้างหลักสูตรใหม่" passes through the router. */
interface IntakeRouteState {
  creating?: boolean
}

export default function Intake() {
  const navigate = useNavigate()
  const location = useLocation()
  const { programId, setProgramId } = useProgram()
  const [form, setForm] = useState<FormState>(INITIAL)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  // The page is a form for one program, not a create-only form: with a program
  // selected it shows that program and saves back to it. `creating` is how a
  // designer starts a second one without first deselecting the first.
  //
  // It starts true when the caller said so, which is the only way to arrive here
  // on an empty form: a program id lives in localStorage and outlives every
  // mount, so the default is edit mode and "+ สร้างหลักสูตรใหม่" used to land on
  // the current curriculum's own data with a submit that saved back over it.
  // Read once as the initial value rather than in an effect — an effect would
  // let the loader populate the fields first and then blank them, and would fire
  // again on a later navigation the designer did not ask to reset.
  const [creating, setCreating] = useState(
    () => (location.state as IntakeRouteState | null)?.creating === true
  )
  const [loaded, setLoaded] = useState<FormState | null>(null)
  const editing = Boolean(programId) && !creating

  useEffect(() => {
    if (!programId || creating) return
    let cancelled = false
    api
      .get<Partial<FormState>>(`/programs/${programId}`)
      .then((r) => {
        if (cancelled) return
        const next: FormState = {
          university: r.data.university ?? '',
          faculty: r.data.faculty ?? '',
          field: r.data.field ?? '',
          scope_th: r.data.scope_th ?? '',
          degree_level: r.data.degree_level ?? 'bachelor',
          duration_years: r.data.duration_years ?? 4,
        }
        setForm(next)
        // Kept so the save can tell which fields actually moved — two of them
        // invalidate the extracted skills and the designer has to be told.
        setLoaded(next)
      })
      .catch(() => setError('โหลดข้อมูลหลักสูตรไม่สำเร็จ — ตรวจสอบว่า backend รันอยู่'))
    return () => {
      cancelled = true
    }
  }, [programId, creating])

  function startNewProgram() {
    setCreating(true)
    setForm(INITIAL)
    setLoaded(null)
    setError('')
    setSuccess('')
  }

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
    const payload = {
      university: form.university,
      faculty: form.faculty,
      field: form.field,
      scope_th: form.scope_th.trim(),
      degree_level: form.degree_level,
      duration_years: Number(form.duration_years),
    }
    try {
      if (editing) {
        await api.put(`/programs/${programId}`, payload)
        setLoaded({ ...form, scope_th: payload.scope_th })
        // Only these two reach the skill-extraction cache key, so only these two
        // leave the stored skills answering a question nobody is asking any more.
        const stale =
          loaded !== null &&
          (loaded.field !== payload.field || loaded.scope_th.trim() !== payload.scope_th)
        setSuccess(
          stale
            ? 'บันทึกแล้ว — สาขาวิชาหรือขอบเขตเปลี่ยนไป ทักษะที่สกัดไว้เดิมยังตัดสินด้วยค่าเก่าอยู่ ให้รัน "สกัดทักษะ" ใหม่ทั้งโปรแกรม'
            : 'บันทึกการแก้ไขแล้ว'
        )
      } else {
        const resp = await api.post('/programs/', payload)
        const newId = resp.data.program_id
        setProgramId(newId)
        setCreating(false)
        setSuccess(`บันทึกหลักสูตร "${form.field}" สำเร็จ (รหัส: ${newId})`)
      }
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
          {editing
            ? 'ข้อมูลของหลักสูตรที่กำลังทำอยู่ — แก้ไขแล้วกดบันทึกได้'
            : 'กรอกข้อมูลพื้นฐานของหลักสูตรเพื่อเริ่มกระบวนการออกแบบ OBE'}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          วิสัยทัศน์ พันธกิจ และอัตลักษณ์ ให้บันทึกเป็นหลักฐานที่หน้า Stakeholder Needs
          (ประเภท "วิสัยทัศน์/พันธกิจ/อัตลักษณ์")
        </p>
        {programId && (
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span className="inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500"></span>
              {editing ? `กำลังแก้ไข: ${programId}` : `หลักสูตรปัจจุบัน: ${programId}`}
            </span>
            {editing ? (
              <button
                type="button"
                onClick={startNewProgram}
                className="cursor-pointer text-xs text-gray-500 underline underline-offset-2 hover:text-gray-700"
              >
                สร้างหลักสูตรใหม่แทน
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="cursor-pointer text-xs text-gray-500 underline underline-offset-2 hover:text-gray-700"
              >
                กลับไปแก้ไข {programId}
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 mb-4 text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="mb-4 flex items-center justify-between gap-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
          <span>✓ {success}</span>
          {/* After an edit the next step is whichever stage the change
              invalidated, so the page does not pretend to know it. */}
          {!editing && (
            <button
              onClick={() => navigate('/stakeholder-needs')}
              className="ml-4 font-medium underline hover:text-green-900"
            >
              ไปที่หน้าหลักฐาน →
            </button>
          )}
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
          {loading
            ? 'กำลังบันทึก...'
            : editing
              ? 'บันทึกการแก้ไข'
              : 'บันทึกและเริ่มกระบวนการ'}
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
