import { useEffect, useRef, useState, type FormEvent } from 'react'
import { answerKeyRequest, onKeyRequested } from '../api/apiKey'

/** Mounted once in the app shell. Opens when a request comes back 401. */
export default function ApiKeyDialog() {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(
    () =>
      onKeyRequested(() => {
        setValue('')
        setOpen(true)
      }),
    [],
  )

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  if (!open) return null

  function close(key: string | null) {
    setOpen(false)
    setValue('')
    answerKeyRequest(key)
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const key = value.trim()
    if (key) close(key)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-graphite/40 px-4"
      onKeyDown={(e) => {
        if (e.key === 'Escape') close(null)
      }}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="api-key-title"
        onSubmit={handleSubmit}
        className="panel w-full max-w-sm p-5"
      >
        <h2 id="api-key-title" className="section-title">
          กรอก API key
        </h2>
        <input
          ref={inputRef}
          type="password"
          autoComplete="off"
          aria-labelledby="api-key-title"
          className="input mt-3"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <p className="field-hint">ขอ key จากผู้ดูแลระบบ — เก็บไว้เฉพาะแท็บนี้จนกว่าจะปิด</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="btn btn-quiet" onClick={() => close(null)}>
            ยกเลิก
          </button>
          <button type="submit" className="btn btn-primary" disabled={!value.trim()}>
            บันทึก
          </button>
        </div>
      </form>
    </div>
  )
}
