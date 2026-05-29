# React UI — Intake & Evidence Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace placeholder Intake and StakeholderNeeds pages with full, functional forms matching Streamlit functionality (program intake + evidence management + document upload), using Tailwind CSS v4 for friendly Thai UX.

**Architecture:** Add Tailwind CSS v4 via `@tailwindcss/vite` plugin (no config file needed). Shared `useProgram` hook stores `program_id` in localStorage so Intake → navigate → StakeholderNeeds without losing context. API auth is disabled in dev mode when `API_KEY` is not set in `.env` — no auth header needed. File upload uses browser `FileReader` API (client-side text extraction) and posts as evidence — no new backend endpoint required.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind CSS v4, `@tailwindcss/vite`, axios (existing)

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Modify | `frontend/package.json` | add tailwindcss + @tailwindcss/vite dev deps |
| Modify | `frontend/vite.config.ts` | add tailwindcss() plugin |
| Modify | `frontend/src/index.css` | replace boilerplate with @import "tailwindcss" |
| Create | `frontend/src/hooks/useProgram.ts` | localStorage program_id state shared between pages |
| Modify | `frontend/src/pages/Intake.tsx` | full 10-field program form → POST /programs/ |
| Modify | `frontend/src/pages/StakeholderNeeds.tsx` | evidence form + file upload + evidence list |

---

## Task 1: Add Tailwind CSS v4

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Install Tailwind v4 and Vite plugin**

Run from project root `E:\SideProject\Agent-Curriculum-Design`:

```powershell
cd frontend
npm install -D tailwindcss @tailwindcss/vite
cd ..
```

Expected: `frontend/package.json` devDependencies now includes `tailwindcss` and `@tailwindcss/vite`.

- [ ] **Step 2: Overwrite `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/programs': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 3: Overwrite `frontend/src/index.css`**

```css
@import "tailwindcss";

body {
  margin: 0;
  background: #f8fafc;
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```powershell
cd frontend; npx tsc --noEmit; cd ..
```

Expected: 0 errors. (A warning about `@tailwindcss/vite` types is acceptable — it's a Vite plugin, not a TypeScript module.)

- [ ] **Step 5: Commit**

```
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/index.css
git commit -m "feat: add Tailwind CSS v4 for UI styling"
```

---

## Task 2: useProgram hook

**Files:**
- Create: `frontend/src/hooks/useProgram.ts`

- [ ] **Step 1: Create `frontend/src/hooks/` directory**

```powershell
New-Item -ItemType Directory -Force frontend/src/hooks
```

- [ ] **Step 2: Create `frontend/src/hooks/useProgram.ts`**

```ts
import { useState, useCallback } from 'react'

const STORAGE_KEY = 'ca_program_id'

export function useProgram() {
  const [programId, _set] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? ''
  )

  const setProgramId = useCallback((id: string) => {
    if (id) {
      localStorage.setItem(STORAGE_KEY, id)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
    _set(id)
  }, [])

  return { programId, setProgramId }
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```powershell
cd frontend; npx tsc --noEmit; cd ..
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```
git add frontend/src/hooks/
git commit -m "feat: add useProgram hook with localStorage persistence"
```

---

## Task 3: Intake.tsx — full program form

**Files:**
- Modify: `frontend/src/pages/Intake.tsx`

- [ ] **Step 1: Overwrite `frontend/src/pages/Intake.tsx`**

```tsx
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
  program_id: string
  name_th: string
  name_en: string
  field: string
  degree_level: string
  duration_years: number
  faculty: string
  university: string
  vision_th: string
  objectives_raw: string
}

const INITIAL: FormState = {
  program_id: '', name_th: '', name_en: '', field: '',
  degree_level: 'bachelor', duration_years: 4,
  faculty: '', university: '', vision_th: '', objectives_raw: '',
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
      'program_id', 'name_th', 'name_en', 'field',
      'faculty', 'university', 'vision_th', 'objectives_raw',
    ]
    if (required.some(k => !String(form[k]).trim())) {
      setError('กรุณากรอกข้อมูลที่มีเครื่องหมาย * ให้ครบถ้วน')
      return
    }

    const objectives = form.objectives_raw
      .split('\n')
      .map(l => l.trim())
      .filter(Boolean)

    setLoading(true)
    try {
      await api.post('/programs/', {
        program_id: form.program_id,
        name_th: form.name_th,
        name_en: form.name_en,
        field: form.field,
        degree_level: form.degree_level,
        duration_years: Number(form.duration_years),
        faculty: form.faculty,
        university: form.university,
        vision_th: form.vision_th,
        program_objectives_th: objectives,
      })
      setProgramId(form.program_id)
      setSuccess(`บันทึกหลักสูตร "${form.program_id}" สำเร็จ`)
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
        {/* Row 1 */}
        <div className="grid grid-cols-2 gap-4">
          <Field label="รหัสหลักสูตร *" name="program_id" value={form.program_id} onChange={handleChange} placeholder="cs-2025" />
          <Field label="สาขาวิชา *" name="field" value={form.field} onChange={handleChange} placeholder="Computer Science" />
        </div>

        {/* Row 2 */}
        <div className="grid grid-cols-2 gap-4">
          <Field label="ชื่อหลักสูตร (ภาษาไทย) *" name="name_th" value={form.name_th} onChange={handleChange} />
          <Field label="ชื่อหลักสูตร (ภาษาอังกฤษ) *" name="name_en" value={form.name_en} onChange={handleChange} />
        </div>

        {/* Row 3 */}
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

        {/* Row 4 */}
        <Field label="คณะ *" name="faculty" value={form.faculty} onChange={handleChange} />

        {/* Vision */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">วิสัยทัศน์หลักสูตร (ภาษาไทย) *</label>
          <textarea
            name="vision_th" rows={3} value={form.vision_th} onChange={handleChange}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        {/* Objectives */}
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
```

- [ ] **Step 2: Verify TypeScript compiles**

```powershell
cd frontend; npx tsc --noEmit; cd ..
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/Intake.tsx
git commit -m "feat: implement full program intake form (Stage 1)"
```

---

## Task 4: StakeholderNeeds.tsx — evidence form + list + upload

**Files:**
- Modify: `frontend/src/pages/StakeholderNeeds.tsx`

- [ ] **Step 1: Overwrite `frontend/src/pages/StakeholderNeeds.tsx`**

```tsx
import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useProgram } from '../hooks/useProgram'

const STAKEHOLDER_LABELS: Record<string, string> = {
  employer:            'นายจ้าง',
  alumni:              'ศิษย์เก่า',
  professional_council:'สภาวิชาชีพ',
  accreditation_body:  'หน่วยงานประเมิน',
  university:          'มหาวิทยาลัย',
  community:           'ชุมชน',
  subject_benchmark:   'มาตรฐานสาขา',
  peer_program:        'หลักสูตรเทียบเคียง',
}

const CLASS_STYLE: Record<string, { label: string; cls: string }> = {
  need:         { label: 'ความต้องการ',   cls: 'bg-green-100 text-green-700' },
  requirement:  { label: 'ข้อกำหนด',      cls: 'bg-blue-100 text-blue-700' },
  want:         { label: 'ความปรารถนา',  cls: 'bg-yellow-100 text-yellow-700' },
  unclassified: { label: 'ยังไม่จำแนก',  cls: 'bg-gray-100 text-gray-500' },
}

interface EvidenceItem {
  evidence_id: string
  stakeholder_type: string
  source_name: string
  raw_text_th: string
  classification: string
}

interface EvidencePayload {
  evidence_id: string
  program_id: string
  stakeholder_type: string
  source_name: string
  raw_text_th: string
}

export default function StakeholderNeeds() {
  const navigate = useNavigate()
  const { programId, setProgramId } = useProgram()
  const [pidInput, setPidInput] = useState('')
  const [stakeholderType, setStakeholderType] = useState('employer')
  const [sourceName, setSourceName] = useState('')
  const [rawText, setRawText] = useState('')
  const [items, setItems] = useState<EvidenceItem[]>([])
  const [loadingList, setLoadingList] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const fetchEvidence = useCallback(async (pid: string) => {
    setLoadingList(true)
    setError('')
    try {
      const res = await api.get<EvidenceItem[]>(`/programs/${pid}/evidence/`)
      setItems(res.data)
    } catch {
      setError('โหลดหลักฐานไม่ได้ — ตรวจสอบว่า backend รันอยู่')
    } finally {
      setLoadingList(false)
    }
  }, [])

  useEffect(() => {
    if (programId) fetchEvidence(programId)
  }, [programId, fetchEvidence])

  async function postEvidence(payload: EvidencePayload) {
    setSubmitting(true)
    setError('')
    setSuccess('')
    try {
      await api.post(`/programs/${payload.program_id}/evidence/`, payload)
      setSuccess('เพิ่มหลักฐานสำเร็จ')
      await fetchEvidence(payload.program_id)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status: number } }
      if (axiosErr.response) {
        setError(`API error ${axiosErr.response.status}`)
      } else {
        setError('เชื่อมต่อ API ไม่ได้')
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function handleFormSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!programId) { setError('กรุณาระบุรหัสหลักสูตรก่อน'); return }
    if (!sourceName.trim() || !rawText.trim()) { setError('กรุณากรอกแหล่งที่มาและข้อความหลักฐาน'); return }
    await postEvidence({
      evidence_id: crypto.randomUUID(),
      program_id: programId,
      stakeholder_type: stakeholderType,
      source_name: sourceName.trim(),
      raw_text_th: rawText.trim(),
    })
    setSourceName('')
    setRawText('')
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !programId) return
    const text = await file.text()
    if (!text.trim()) { setError('ไฟล์ว่างเปล่า'); return }
    await postEvidence({
      evidence_id: crypto.randomUUID(),
      program_id: programId,
      stakeholder_type: stakeholderType,
      source_name: file.name,
      raw_text_th: text,
    })
    if (fileRef.current) fileRef.current.value = ''
  }

  function handleSetProgram() {
    const pid = pidInput.trim()
    if (!pid) return
    setProgramId(pid)
    fetchEvidence(pid)
  }

  return (
    <div className="max-w-3xl mx-auto text-left space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-800">ขั้นตอนที่ 2 — หลักฐานผู้มีส่วนได้ส่วนเสีย</h1>
        <p className="text-gray-500 text-sm mt-1">
          เพิ่มหลักฐานจากแหล่งต่างๆ เพื่อใช้ในการสังเคราะห์ PLO
        </p>
      </div>

      {/* Program ID bar */}
      {!programId ? (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <p className="text-sm text-amber-800 mb-3">
            ยังไม่ได้เลือกหลักสูตร —{' '}
            <button onClick={() => navigate('/')} className="underline font-medium">
              ไปที่ขั้นตอนที่ 1
            </button>{' '}
            หรือระบุรหัสหลักสูตรที่นี่
          </p>
          <div className="flex gap-2">
            <input
              value={pidInput} onChange={e => setPidInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSetProgram()}
              placeholder="รหัสหลักสูตร เช่น cs-2025"
              className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={handleSetProgram}
              className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition-colors"
            >
              ยืนยัน
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2.5 flex items-center justify-between">
          <span className="text-sm text-blue-700">
            หลักสูตร: <strong>{programId}</strong>
            <span className="text-blue-400 ml-2">— พบ {items.length} หลักฐาน</span>
          </span>
          <button
            onClick={() => { setProgramId(''); setItems([]) }}
            className="text-xs text-blue-400 hover:text-blue-700 transition-colors"
          >
            เปลี่ยน
          </button>
        </div>
      )}

      {/* Alerts */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm flex justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="ml-4 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}
      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm flex justify-between">
          <span>✓ {success}</span>
          <button onClick={() => setSuccess('')} className="ml-4 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      {/* Add Evidence */}
      {programId && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-base font-semibold text-gray-700 mb-4">เพิ่มหลักฐานใหม่</h2>
          <form onSubmit={handleFormSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  ประเภทผู้มีส่วนได้ส่วนเสีย
                </label>
                <select
                  value={stakeholderType} onChange={e => setStakeholderType(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {Object.entries(STAKEHOLDER_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">แหล่งที่มา *</label>
                <input
                  value={sourceName} onChange={e => setSourceName(e.target.value)}
                  placeholder="บริษัท ABC / ผู้ประกอบการ XYZ"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ข้อความหลักฐาน (ภาษาไทย) *
              </label>
              <textarea
                value={rawText} onChange={e => setRawText(e.target.value)}
                rows={4}
                placeholder="วางข้อความที่ได้จากการสัมภาษณ์ แบบสอบถาม หรือเอกสาร..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>

            <div className="flex items-center gap-4">
              <button
                type="submit" disabled={submitting}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors cursor-pointer disabled:cursor-not-allowed"
              >
                {submitting ? 'กำลังบันทึก...' : 'เพิ่มหลักฐาน'}
              </button>

              <div className="h-4 w-px bg-gray-200" />

              {/* File upload trigger */}
              <label className="flex items-center gap-2 text-sm text-gray-500 hover:text-blue-600 cursor-pointer transition-colors group">
                <svg
                  className="w-4 h-4 group-hover:text-blue-600"
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                อัปโหลดเอกสาร
                <span className="text-xs text-gray-400">(.txt, .md, .csv)</span>
                <input
                  ref={fileRef} type="file" accept=".txt,.md,.csv"
                  onChange={handleFileUpload} className="hidden"
                />
              </label>
            </div>
          </form>
        </div>
      )}

      {/* Evidence list */}
      {programId && (
        <div>
          <h2 className="text-base font-semibold text-gray-700 mb-3">หลักฐานทั้งหมด</h2>
          {loadingList ? (
            <div className="text-center text-gray-400 py-8 text-sm">กำลังโหลด...</div>
          ) : items.length === 0 ? (
            <div className="text-center text-gray-400 py-10 text-sm bg-white rounded-xl border border-gray-100">
              ยังไม่มีหลักฐาน — เพิ่มหลักฐานด้านบน
            </div>
          ) : (
            <div className="space-y-2">
              {items.map(item => {
                const cs = CLASS_STYLE[item.classification] ?? CLASS_STYLE.unclassified
                const typeLabel = STAKEHOLDER_LABELS[item.stakeholder_type] ?? item.stakeholder_type
                return (
                  <details
                    key={item.evidence_id}
                    className="bg-white rounded-lg border border-gray-100 shadow-sm group open:shadow-md transition-shadow"
                  >
                    <summary className="flex items-center justify-between px-4 py-3 cursor-pointer list-none select-none">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-medium text-gray-700 text-sm shrink-0">{typeLabel}</span>
                        <span className="text-gray-300">—</span>
                        <span className="text-gray-600 text-sm truncate">{item.source_name}</span>
                      </div>
                      <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full shrink-0 ml-3 ${cs.cls}`}>
                        {cs.label}
                      </span>
                    </summary>
                    <div className="px-4 pb-4 pt-2 border-t border-gray-50">
                      <p className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{item.raw_text_th}</p>
                      <p className="text-xs text-gray-300 mt-3 font-mono">{item.evidence_id}</p>
                    </div>
                  </details>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```powershell
cd frontend; npx tsc --noEmit; cd ..
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/StakeholderNeeds.tsx
git commit -m "feat: implement evidence management with form, list, and file upload (Stage 2)"
```

---

## Task 5: Smoke test

**Files:** (no changes)

- [ ] **Step 1: Backend tests still pass**

```powershell
cd E:\SideProject\Agent-Curriculum-Design
uv run pytest --tb=no -q
```

Expected: `40 passed`

- [ ] **Step 2: Frontend TypeScript clean**

```powershell
cd frontend; npx tsc --noEmit; cd ..
```

Expected: 0 errors.

- [ ] **Step 3: Dev server starts**

```powershell
cd frontend
npm run dev
```

Open http://localhost:5173 in browser. Verify:
- Stage 1 page shows the full form with all fields
- Stage 2 page shows the evidence form and file upload button
- Nav links between stages work

Press Ctrl+C to stop.

- [ ] **Step 4: Final commit (if any pending changes)**

If there are no pending changes, skip this step.

---

## Self-Review

**Spec coverage:**
- ✅ รับข้อมูล program intake (Task 3) — matches 1_intake.py fields
- ✅ อัปโหลดเอกสาร (Task 4 file upload) — FileReader API reads .txt/.md/.csv
- ✅ เพิ่มหลักฐานแบบ manual (Task 4 form) — matches 2_evidence.py form
- ✅ แสดงรายการหลักฐาน (Task 4 list) — expandable cards with classification badges
- ✅ Friendly UX — Tailwind CSS, loading states, error/success alerts, nav between stages

**Placeholder scan:** ไม่มี TBD, TODO, หรือ incomplete sections.

**Type consistency:**
- `useProgram` → `{ programId, setProgramId }` — ใช้ consistent ทั้ง Intake และ StakeholderNeeds
- `EvidencePayload` interface ใน StakeholderNeeds → fields ตรงกับ `StakeholderEvidence` Pydantic model
- `FormState` interface → fields ตรงกับ POST /programs/ payload

**Ambiguity:** `crypto.randomUUID()` ต้องการ HTTPS หรือ localhost — dev ที่ localhost:5173 ใช้ได้ปกติ.
