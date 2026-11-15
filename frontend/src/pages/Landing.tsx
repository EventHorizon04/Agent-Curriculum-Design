import { useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { CREATING_INTAKE } from '../constants/intakeMode'

const STEPS = [
  {
    n: 'STEP 1',
    title: 'Program',
    body: 'กรอกมหาวิทยาลัย คณะ สาขา ระดับ และเลือก Multi-agent หรือ Single-agent',
    approve: false,
  },
  {
    n: 'STEP 2',
    title: 'Evidence',
    body: 'ใส่ข้อมูลจากผู้ใช้บัณฑิต ศิษย์เก่า สภาวิชาชีพ และวิสัยทัศน์ของสถาบัน',
    approve: false,
  },
  {
    n: 'STEP 3',
    title: 'Needs',
    body: 'AI สรุปความต้องการจากหลักฐาน คุณรวม แยก หรือตัด Need ได้',
    approve: true,
  },
  {
    n: 'STEP 4',
    title: 'PLO',
    body: 'AI ร่าง PLO 6–10 ข้อ ตรวจ SMART แล้วออก Report พร้อมใช้ใน มคอ.2',
    approve: true,
  },
]

const MODES = [
  {
    tag: 'แนะนำ',
    title: 'Multi-agent',
    points: [
      'Agent แยกตามขั้น: Skill extraction, Need, PLO, Review',
      'โหวตหลายรอบ ตรวจซ้ำอัตโนมัติ',
      'ละเอียดกว่า ใช้เวลานานกว่า',
    ],
  },
  {
    tag: 'ทดลอง',
    title: 'Single-agent',
    points: [
      'LLM ตัวเดียวอ่านหลักฐานแล้วเขียน Need และ PLO เอง',
      'เร็วกว่า เรียก AI น้อยกว่า',
      'ผลแต่ละรอบต่างกันได้มากกว่า',
    ],
  },
]

const TRUST = [
  { big: '100%', body: 'ทุก PLO สาวกลับถึง Need และหลักฐานต้นทาง' },
  { big: 'SMART', body: 'ตรวจทุกข้อด้วยกฎที่เขียนเป็นโค้ด ไม่ใช่ความเห็นของ AI อย่างเดียว' },
  { big: 'HITL', body: 'Human-in-the-loop: ไม่มีขั้นไหนข้ามการอนุมัติของคุณ' },
]

const BAND = 'px-4 py-16 sm:py-[88px]'
const WRAP = 'mx-auto max-w-[980px]'
const H2 = 'mb-3 text-center text-[clamp(28px,4.4vw,48px)] font-bold leading-[1.25] tracking-tight'
const SUB = 'mx-auto mb-12 max-w-[36em] text-center text-[17px] leading-[1.7] sm:text-[19px]'

/**
 * Static front page: what the tool does and how to use it in four steps. It
 * calls no API, so it renders the same with or without a program selected.
 */
export default function Landing() {
  const navigate = useNavigate()
  const { hash } = useLocation()
  const start = () => navigate('/intake', { state: CREATING_INTAKE })

  useEffect(() => {
    if (hash === '#steps') {
      document.getElementById('steps')?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [hash])

  return (
    <div className="text-graphite">
      <section className="bg-paper px-4 pb-16 pt-16 text-center sm:pt-[88px]">
        <div className="eyebrow text-[17px]">Curriculum Design Agent</div>
        <h1 className="mx-auto mb-4 mt-2 max-w-[15ch] text-[clamp(34px,6vw,64px)] font-bold leading-[1.25] tracking-tight">
          จากเสียงผู้มีส่วนได้ส่วนเสีย สู่ PLO ที่ตรวจสอบได้
        </h1>
        <p className="mx-auto mb-8 max-w-[34em] text-[clamp(17px,2.2vw,22px)] leading-[1.7] text-pencil">
          AI ช่วยอาจารย์สรุปความต้องการจากหลักฐานจริง แล้วร่าง PLO ตามหลัก OBE และเกณฑ์ อว.
          โดยคุณเป็นผู้ตัดสินทุกขั้น
        </p>
        <div className="flex flex-wrap items-center justify-center gap-6">
          <button type="button" onClick={start} className="btn btn-primary">
            เริ่มหลักสูตรใหม่
          </button>
          <a href="#steps" className="btn-text text-[17px]">
            ดูวิธีใช้ใน 4 ขั้น ›
          </a>
        </div>
        <div className="mx-auto mt-14 max-w-[880px] rounded-[22px] bg-sheet p-5 text-left shadow-[0_30px_80px_rgba(0,0,0,0.12)] sm:p-[22px]">
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-bold">PLO1</span>
            <span className="chip">Skill</span>
            <span className="chip">Evaluate</span>
            <span className="chip chip-stamp">SMART ✓</span>
          </div>
          <p className="record mb-3.5">
            ประเมินและปรับปรุงผลลัพธ์การแปลเอกสารธุรกิจภาษาไทย–จีน
            โดยใช้เครื่องมือ AI ช่วยแปลให้ถูกต้องตามบริบททางธุรกิจ
          </p>
          <div className="text-[13px] text-lead">
            อ้าง 2 Needs · หลักฐาน 4 รายการ จากผู้ใช้บัณฑิต ศิษย์เก่า อาจารย์
          </div>
        </div>
      </section>

      <section id="steps" className={`${BAND} scroll-mt-16`}>
        <div className={WRAP}>
          <h2 className={H2}>ใช้งานใน 4 ขั้น</h2>
          <p className={`${SUB} text-pencil`}>
            แต่ละขั้น AI ทำงานให้ แล้วหยุดรอให้คุณตรวจและอนุมัติก่อนไปขั้นต่อไป
          </p>
          <div className="grid grid-cols-1 gap-4 min-[760px]:grid-cols-4">
            {STEPS.map((s) => (
              <div key={s.title} className="rounded-[18px] bg-paper px-6 py-7">
                <div className="text-[13px] font-semibold tracking-wide text-stamp">{s.n}</div>
                <h3 className="mb-1.5 mt-2.5 text-[21px] font-semibold tracking-tight">{s.title}</h3>
                <p className="m-0 text-[15px] leading-[1.7] text-pencil">{s.body}</p>
                {s.approve && (
                  <span className="mt-3.5 inline-block rounded-full bg-stamp-wash px-2.5 py-1 text-xs font-semibold text-stamp">
                    คุณอนุมัติ
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={`${BAND} bg-paper`}>
        <div className={WRAP}>
          <h2 className={H2}>เลือกวิธีให้ AI ทำงาน</h2>
          <p className={`${SUB} text-pencil`}>เลือกครั้งเดียวตอนสร้างหลักสูตร</p>
          <div className="grid grid-cols-1 gap-4 min-[760px]:grid-cols-2">
            {MODES.map((m) => (
              <div key={m.title} className="rounded-[18px] bg-sheet px-6 py-7">
                <div className="text-[13px] font-semibold tracking-wide text-stamp">{m.tag}</div>
                <h3 className="mb-1.5 mt-2.5 text-[28px] font-semibold tracking-tight">{m.title}</h3>
                <ul className="mt-3 list-disc space-y-1 pl-[18px] text-[15px] leading-[1.7] text-pencil">
                  {m.points.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={BAND}>
        <div className={`${WRAP} grid grid-cols-1 gap-8 text-center min-[760px]:grid-cols-3`}>
          {TRUST.map((t) => (
            <div key={t.big}>
              <div className="text-[40px] font-bold leading-tight tracking-tight text-stamp">{t.big}</div>
              <p className="mt-1 leading-[1.7] text-pencil">{t.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className={`${BAND} bg-stamp-deep text-white`}>
        <div className={`${WRAP} text-center`}>
          <h2 className={H2}>พร้อมเริ่มหลักสูตรแรกแล้วหรือยัง</h2>
          <p className={`${SUB} text-white/75`}>ใช้เวลากรอกข้อมูลหลักสูตรไม่ถึง 2 นาที</p>
          <div className="flex flex-wrap items-center justify-center gap-6">
            <button
              type="button"
              onClick={start}
              className="btn bg-white text-stamp-deep hover:bg-white/90"
            >
              เริ่มหลักสูตรใหม่
            </button>
            <Link to="/my-programs" className="text-[17px] font-medium text-marker hover:underline">
              หลักสูตรของฉัน ›
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}
