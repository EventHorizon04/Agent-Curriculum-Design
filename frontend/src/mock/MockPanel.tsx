import { useEffect, useState, useSyncExternalStore } from 'react'
import { SCENARIOS, getControls, isScenarioName, setControls, subscribeControls, type ScenarioName } from './db'
import { seedScenario } from './scenarios'

/**
 * The mock's control surface. Always on screen — as a marker-yellow "MOCK"
 * pill when collapsed — so nobody reads seeded rows as real curriculum data.
 *
 * Marker is the design system's "look at this" ink, which is exactly what the
 * pill has to say. Collapsed by default on narrow screens, where an open panel
 * would sit over the page's own controls.
 */
export default function MockPanel() {
  const controls = useSyncExternalStore(subscribeControls, getControls)
  const [open, setOpen] = useState(() => window.innerWidth >= 640)
  const [scenario, setScenario] = useState<ScenarioName>(controls.scenario)

  // Room below the page's last element for whatever the panel covers, so it
  // never sits on top of the NextStageLink button at the foot of a stage page.
  useEffect(() => {
    document.body.style.paddingBottom = open ? '19rem' : '3.5rem'
  }, [open])

  const reset = () => {
    seedScenario(scenario)
    // Every page and the shell re-read from the fresh database.
    window.location.assign('/')
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="ข้อมูลจำลอง — เปิดแผงควบคุม"
        className="data fixed right-3 bottom-3 z-50 rounded-[3px] border border-marker-ink/40 bg-marker px-3 py-1 text-xs font-semibold tracking-[0.12em] text-graphite shadow-[0_1px_3px_rgb(0_0_0/0.18)] hover:bg-marker-wash"
      >
        MOCK
      </button>
    )
  }

  return (
    <aside
      aria-label="แผงควบคุมข้อมูลจำลอง"
      className="panel fixed right-3 bottom-3 z-50 w-[min(19rem,calc(100vw-1.5rem))] border-marker-ink/40 p-3 text-left shadow-[0_2px_10px_rgb(0_0_0/0.14)]"
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="data rounded-[2px] bg-marker px-1.5 text-xs font-semibold tracking-[0.12em] text-graphite">
          MOCK
        </span>
        <p className="eyebrow min-w-0 flex-1">ข้อมูลจำลอง ไม่ใช่ข้อมูลจริง</p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="ย่อแผงควบคุม"
          className="btn btn-sm btn-quiet px-1.5"
        >
          ย่อ
        </button>
      </div>

      <label htmlFor="mock-scenario" className="field-label text-xs">
        สถานการณ์
      </label>
      <div className="flex gap-1.5">
        <select
          id="mock-scenario"
          value={scenario}
          onChange={(e) => {
            if (isScenarioName(e.target.value)) setScenario(e.target.value)
          }}
          className="input min-w-0 flex-1 py-1 text-xs"
        >
          {SCENARIOS.map((s) => (
            <option key={s.name} value={s.name}>
              {s.label}
            </option>
          ))}
        </select>
        <button type="button" onClick={reset} className="btn btn-sm btn-secondary">
          รีเซ็ต
        </button>
      </div>
      <p className="field-hint">รีเซ็ตล้างทุกอย่างที่ทำไว้ แล้วโหลดสถานการณ์ที่เลือกใหม่</p>

      <div className="mt-3 space-y-2 border-t border-hair pt-3">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-graphite">
          <input
            type="checkbox"
            checked={controls.latency}
            onChange={(e) => setControls({ latency: e.target.checked })}
            className="accent-stamp"
          />
          หน่วงเวลาเหมือนจริง
          <span className="text-lead">(ปิด = ตอบทันที)</span>
        </label>

        <label className="flex cursor-pointer items-center gap-2 text-xs text-graphite">
          <input
            type="checkbox"
            checked={controls.validationEnabled}
            onChange={(e) => setControls({ validationEnabled: e.target.checked })}
            className="accent-stamp"
          />
          ระบบเปิดผู้ตรวจ SMART
          <span className="text-lead">(ปิด = VALIDATION_PROVIDER ว่าง)</span>
        </label>

        <ArmButton
          armed={controls.failNextRequest}
          label="request ถัดไป error"
          hint="ตอบ 500 หนึ่งครั้ง"
          onToggle={() => setControls({ failNextRequest: !controls.failNextRequest })}
        />
        <ArmButton
          armed={controls.failNextRun}
          label="run ถัดไปล้มเหลว"
          hint="ปุ่ม Run หรือ session ขั้นถัดไป"
          onToggle={() => setControls({ failNextRun: !controls.failNextRun })}
        />
      </div>

      <p className="mt-3 border-t border-hair pt-2 text-[0.6875rem] leading-snug text-pencil">
        ทุก request ตอบจากเบราว์เซอร์ ไม่มีอะไรส่งไปที่ backend · พอร์ต 5174
      </p>
    </aside>
  )
}

function ArmButton({
  armed,
  label,
  hint,
  onToggle,
}: {
  armed: boolean
  label: string
  hint: string
  onToggle: () => void
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={armed}
        className={`btn btn-sm ${armed ? 'btn-danger' : 'btn-secondary'}`}
      >
        {label}
      </button>
      {armed ? (
        <span className="chip chip-mandate">ตั้งไว้แล้ว</span>
      ) : (
        <span className="text-[0.6875rem] text-lead">{hint}</span>
      )}
    </div>
  )
}
