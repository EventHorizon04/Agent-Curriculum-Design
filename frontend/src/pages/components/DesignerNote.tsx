export const NOTE_MAX = 500

export default function DesignerNote({
  value,
  onChange,
  disabled = false,
}: {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
}) {
  const remaining = NOTE_MAX - value.length
  return (
    <div className="mb-4 text-left">
      <label htmlFor="designer-note" className="field-label">
        หมายเหตุถึง AI (ไม่บังคับ)
      </label>
      <textarea
        id="designer-note"
        rows={2}
        maxLength={NOTE_MAX}
        disabled={disabled}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="เช่น เน้นทักษะด้าน AI และการวิเคราะห์ข้อมูล"
        className="input resize-none"
      />
      <div className="field-hint flex justify-between gap-3">
        <span>ใช้ชี้แนะถ้อยคำและการเน้นเนื้อหาเท่านั้น ไม่เปลี่ยนหลักฐานอ้างอิง</span>
        <span className="data shrink-0">{remaining}</span>
      </div>
    </div>
  )
}
