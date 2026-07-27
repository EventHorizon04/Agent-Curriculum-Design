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
  degree_level: string
  duration_years: number
  faculty: string
  university: string
  vision_th: string
  mission_th: string
  philosophy_th: string
  institutional_identity_th: string
  student_identity_th: string
  objectives_raw: string
  goals_raw: string
}

const INITIAL: FormState = {
  name_th: '', name_en: '', field: '',
  degree_level: 'bachelor', duration_years: 4,
  faculty: '', university: '', vision_th: '',
  mission_th: '', philosophy_th: '', institutional_identity_th: '',
  student_identity_th: '',
  objectives_raw: '', goals_raw: '',
}

interface ExtractedMetadata {
  vision_th: string | null
  mission_th: string | null
  institutional_identity_th: string | null
  student_identity_th: string | null
}

// The endpoint adds a code-computed warning list on top of the extracted values.
// The extraction prompt permits paraphrase, so a flagged field is a prompt to
// check rather than proof of invention — it is filled in either way.
interface MetadataExtractionResult extends ExtractedMetadata {
  low_grounding_fields: (keyof ExtractedMetadata)[]
}

const FIELD_LABELS: Record<keyof ExtractedMetadata, string> = {
  vision_th: 'วิสัยทัศน์',
  mission_th: 'พันธกิจ',
  institutional_identity_th: 'เอกลักษณ์สถาบัน',
  student_identity_th: 'อัตลักษณ์บัณฑิต',
}

interface SuggestedProgramName {
  name_th: string
  name_en: string
}

interface IscedSuggestion {
  isced_code: string
  field_name_en: string
  field_name_th: string
  rationale_th: string
  suggested_names: SuggestedProgramName[]
}

export default function Intake() {
  const navigate = useNavigate()
  const { programId, setProgramId } = useProgram()
  const [form, setForm] = useState<FormState>(INITIAL)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [entryMode, setEntryMode] = useState<'manual' | 'upload'>('manual')
  const [docFile, setDocFile] = useState<File | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [extractMessage, setExtractMessage] = useState('')
  const [flaggedFields, setFlaggedFields] = useState<string[]>([])
  const [iscedResult, setIscedResult] = useState<IscedSuggestion | null>(null)
  const [iscedCode, setIscedCode] = useState('')
  const [iscedLoading, setIscedLoading] = useState(false)
  const [iscedError, setIscedError] = useState('')

  function switchMode(mode: 'manual' | 'upload') {
    setEntryMode(mode)
    setExtractMessage('')
    if (mode === 'manual') {
      setDocFile(null)
    }
  }

  async function handleExtract() {
    if (!docFile) {
      setExtractMessage('กรุณาเลือกไฟล์ก่อน')
      return
    }
    setExtracting(true)
    setExtractMessage('')
    setFlaggedFields([])
    try {
      const fd = new FormData()
      fd.append('file', docFile)
      const resp = await api.post<MetadataExtractionResult>('/programs/extract-metadata', fd)
      const data = resp.data
      // Compute the merge OUTSIDE the state updater — React StrictMode runs
      // updaters twice, which would duplicate side effects like filled.push.
      const filled: string[] = []
      const updates: Partial<FormState> = {}
      ;(Object.keys(FIELD_LABELS) as (keyof ExtractedMetadata)[]).forEach(key => {
        const value = data[key]
        if (value && !form[key].trim()) {
          updates[key] = value
          filled.push(FIELD_LABELS[key])
        }
      })
      if (filled.length > 0) {
        setForm(prev => ({ ...prev, ...updates }))
      }
      // Warn only about fields actually filled in — a flag on a field the
      // designer had already written themselves is noise.
      const suspect = (data.low_grounding_fields ?? [])
        .filter(key => updates[key] !== undefined)
        .map(key => FIELD_LABELS[key])
      setFlaggedFields(suspect)
      setExtractMessage(
        filled.length > 0
          ? `เติมข้อมูลแล้ว ${filled.length} รายการ (${filled.join(', ')})`
          : 'ไม่พบข้อมูลในเอกสาร'
      )
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status: number; data?: { detail?: string } } }
      setExtractMessage(
        axiosErr.response?.data?.detail ??
          'สกัดข้อมูลไม่สำเร็จ — ตรวจสอบว่า backend รันอยู่'
      )
    } finally {
      setExtracting(false)
    }
  }

  async function handleSuggestIsced() {
    if (!form.name_th.trim() || !form.name_en.trim() || !form.field.trim()) {
      setIscedError('กรุณากรอกชื่อหลักสูตร (ไทย/อังกฤษ) และสาขาวิชาก่อน')
      return
    }
    setIscedLoading(true)
    setIscedError('')
    try {
      const resp = await api.post<IscedSuggestion>('/programs/suggest-isced', {
        name_th: form.name_th,
        name_en: form.name_en,
        field: form.field,
      })
      setIscedResult(resp.data)
      // A fresh suggestion card replaces the old one — clear any previously
      // applied code so the badge can't silently disagree with what's shown.
      setIscedCode('')
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setIscedError(
        axiosErr.response?.data?.detail ?? 'จำแนก ISCED ไม่สำเร็จ — ตรวจสอบว่า backend รันอยู่'
      )
    } finally {
      setIscedLoading(false)
    }
  }

  function applyIscedSuggestion(name: SuggestedProgramName) {
    if (!iscedResult) return
    setForm(prev => ({ ...prev, name_th: name.name_th, name_en: name.name_en }))
    setIscedCode(iscedResult.isced_code)
  }

  function clearIscedCode() {
    setIscedCode('')
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

    const required: (keyof FormState)[] = [
      'name_th', 'name_en', 'field',
      'faculty', 'university', 'vision_th',
      'mission_th', 'philosophy_th', 'objectives_raw', 'goals_raw',
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
        isced_code: iscedCode || null,
        degree_level: form.degree_level,
        duration_years: Number(form.duration_years),
        faculty: form.faculty,
        university: form.university,
        vision_th: form.vision_th,
        mission_th: form.mission_th,
        philosophy_th: form.philosophy_th,
        institutional_identity_th: form.institutional_identity_th || null,
        student_identity_th: form.student_identity_th || null,
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

        <div className="flex items-center gap-3 -mt-1">
          <button
            type="button"
            onClick={handleSuggestIsced}
            disabled={iscedLoading}
            className="text-sm text-blue-600 hover:text-blue-800 underline disabled:text-gray-400 disabled:no-underline cursor-pointer disabled:cursor-not-allowed"
          >
            {iscedLoading ? 'กำลังตรวจสอบ...' : 'ตรวจสอบ ISCED / แนะนำชื่อ'}
          </button>
          {iscedCode && (
            <span className="inline-flex items-center gap-1 bg-green-50 border border-green-200 text-green-700 text-xs font-medium px-2 py-0.5 rounded-full">
              ISCED: {iscedCode}
              <button type="button" onClick={clearIscedCode} className="hover:text-green-900 cursor-pointer">
                ×
              </button>
            </span>
          )}
        </div>

        {iscedError && (
          <p className="text-xs text-red-600 -mt-2">{iscedError}</p>
        )}

        {iscedResult && (
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 space-y-3 -mt-2">
            <div>
              <p className="text-sm font-medium text-gray-800">
                {iscedResult.isced_code} — {iscedResult.field_name_th} ({iscedResult.field_name_en})
              </p>
              <p className="text-xs text-gray-600 mt-1">{iscedResult.rationale_th}</p>
            </div>
            <div className="space-y-2">
              {iscedResult.suggested_names.map((name, i) => (
                <div key={i} className="flex items-center justify-between bg-white rounded-lg border border-gray-200 px-3 py-2">
                  <div className="text-sm">
                    <p className="text-gray-800">{name.name_th}</p>
                    <p className="text-gray-500 text-xs">{name.name_en}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => applyIscedSuggestion(name)}
                    className="text-xs bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg px-3 py-1.5 transition-colors cursor-pointer shrink-0"
                  >
                    ใช้ชื่อนี้
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <Field label="สาขาวิชา *" name="field" value={form.field} onChange={handleChange} placeholder="Computer Science" />

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

        <div className="border-t border-gray-100 pt-5">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            ข้อมูลวิสัยทัศน์ / พันธกิจ / เอกลักษณ์
          </label>
          <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm mb-3">
            <button
              type="button"
              onClick={() => switchMode('manual')}
              className={`px-4 py-1.5 transition-colors ${
                entryMode === 'manual'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              กรอกข้อมูลเอง
            </button>
            <button
              type="button"
              onClick={() => switchMode('upload')}
              className={`px-4 py-1.5 transition-colors ${
                entryMode === 'upload'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              อัปโหลดเอกสารมหาวิทยาลัย
            </button>
          </div>

          {entryMode === 'upload' && (
            <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 space-y-3">
              <p className="text-xs text-gray-600">
                อัปโหลดเอกสาร (มคอ.2 เดิม, ธรรมนูญ, SAR ฯลฯ) ระบบจะสกัดวิสัยทัศน์ พันธกิจ
                เอกลักษณ์สถาบัน และอัตลักษณ์บัณฑิตมาเติมในช่องที่ยังว่างให้อัตโนมัติ
              </p>
              <div className="flex items-center gap-3">
                <input
                  type="file"
                  accept=".pdf,.docx,.doc,.txt"
                  onChange={e => setDocFile(e.target.files?.[0] ?? null)}
                  className="text-sm text-gray-600 file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-white file:text-blue-600 file:text-sm file:cursor-pointer"
                />
                <button
                  type="button"
                  onClick={handleExtract}
                  disabled={extracting || !docFile}
                  className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium rounded-lg px-4 py-1.5 transition-colors cursor-pointer disabled:cursor-not-allowed shrink-0"
                >
                  {extracting ? 'กำลังสกัดข้อมูล…' : 'สกัดข้อมูล'}
                </button>
              </div>
              {extractMessage && (
                <p className="text-xs text-blue-700">{extractMessage}</p>
              )}
              {flaggedFields.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  <p className="font-medium">
                    ตรวจทาน {flaggedFields.length} รายการ: {flaggedFields.join(', ')}
                  </p>
                  <p className="mt-0.5">
                    ข้อความที่เติมให้มีเนื้อหาตรงกับเอกสารต้นฉบับน้อย อาจถูกเรียบเรียงใหม่มากหรือไม่ได้อยู่ในเอกสาร
                    กรุณาเทียบกับต้นฉบับก่อนบันทึก
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">วิสัยทัศน์หลักสูตร (ภาษาไทย) *</label>
          <textarea
            name="vision_th" rows={3} value={form.vision_th} onChange={handleChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

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
          <label className="block text-sm font-medium text-gray-700 mb-1">พันธกิจหลักสูตร (ภาษาไทย) *</label>
          <textarea
            name="mission_th" rows={3} value={form.mission_th} onChange={handleChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">ปรัชญาหลักสูตร (ภาษาไทย) *</label>
          <textarea
            name="philosophy_th" rows={3} value={form.philosophy_th} onChange={handleChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">เอกลักษณ์สถาบัน (ภาษาไทย)</label>
          <textarea
            name="institutional_identity_th" rows={3} value={form.institutional_identity_th} onChange={handleChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">อัตลักษณ์บัณฑิต (ภาษาไทย)</label>
          <textarea
            name="student_identity_th" rows={3} value={form.student_identity_th} onChange={handleChange}
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
