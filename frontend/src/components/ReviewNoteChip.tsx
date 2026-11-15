/** The one marker for "the AI suggests a second look". It never blocks approval. */
export default function ReviewNoteChip({
  count,
  className,
}: {
  count?: number
  className?: string
}) {
  return (
    <span
      className={`chip chip-marker${className ? ` ${className}` : ''}`}
      title="AI แนะนำให้ทบทวน ไม่บล็อกการอนุมัติ — อาจารย์ตัดสินเองว่าจะแก้หรือไม่"
      style={{ cursor: 'help' }}
    >
      {count === undefined ? 'ข้อสังเกต' : `ข้อสังเกต ${count}`}
    </span>
  )
}
