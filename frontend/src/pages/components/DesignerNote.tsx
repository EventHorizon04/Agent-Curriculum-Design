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
      <label htmlFor="designer-note" className="block text-xs font-semibold text-gray-600 mb-1">
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
        className="w-full resize-none rounded-lg border border-gray-300 p-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-gray-50"
      />
      <div className="mt-0.5 flex justify-between text-xs text-gray-400">
        <span>ใช้ชี้แนะถ้อยคำและการเน้นเนื้อหาเท่านั้น ไม่เปลี่ยนหลักฐานอ้างอิง</span>
        <span>{remaining}</span>
      </div>
    </div>
  )
}
