/** Whether the SMART validation agent can run at all — `GET /plos/validation`. */
export interface ValidationStatus {
  enabled: boolean
  /** "" when disabled. */
  model: string
}

/**
 * The per-run switch for the SMART validation agent, beside the run button.
 *
 * Two switches stack here and the page must not blur them: `.env` decides
 * whether the agent can run at all, this box decides whether it runs *this
 * time*. A request cannot turn on an agent the system has off, so when the
 * status says disabled the box is unchecked and locked, with the reason —
 * a ticked box the backend then ignores would claim a check that never ran.
 *
 * Unchecking skips the agent only. The pure-code SMART gate still runs on
 * every PLO (immutable rule 5), which is why the hint says "กฎพื้นฐาน"
 * rather than "ไม่ตรวจ".
 */
export default function ValidationToggle({
  checked,
  onChange,
  status,
  disabled = false,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  /** Null while loading, or when the status could not be read. */
  status: ValidationStatus | null
  disabled?: boolean
}) {
  const systemOff = status?.enabled === false
  const effective = !systemOff && checked

  return (
    <div className="text-left">
      <label
        className={[
          'inline-flex items-center gap-2 text-sm',
          systemOff || disabled ? 'cursor-not-allowed text-lead' : 'cursor-pointer text-graphite',
        ].join(' ')}
      >
        <input
          type="checkbox"
          checked={effective}
          disabled={systemOff || disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-stamp"
        />
        ตรวจด้วยผู้ตรวจ SMART (validation agent)
      </label>
      <p className="field-hint mt-0.5 pl-6">
        {systemOff ? (
          <>ปิดไว้ในการตั้งค่าระบบ (VALIDATION_PROVIDER) — รอบนี้ตรวจด้วยกฎพื้นฐานเท่านั้น</>
        ) : effective ? (
          <>
            ตรวจทีละข้อและสั่งแก้ได้ไม่เกิน 3 รอบ
            {status?.model && (
              <>
                {' · '}โมเดล <span className="data text-graphite">{status.model}</span>
              </>
            )}
          </>
        ) : (
          <>รอบนี้ตรวจด้วยกฎพื้นฐานเท่านั้น — เร็วกว่า แต่ไม่มีข้อสังเกตเรื่องกรรม ระดับ Bloom หรือขอบเขต</>
        )}
      </p>
    </div>
  )
}
