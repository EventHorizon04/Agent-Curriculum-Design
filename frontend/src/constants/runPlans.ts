import type { RunPlan } from '../components/RunProgress'

/**
 * What each long-running stage does, for the wait screen.
 *
 * Written from the pipeline as it runs (CLAUDE.md, stages/), so a designer who
 * reads the list while waiting learns the stage rather than watching a
 * spinner. The durations are the ranges the pages quoted before this file
 * existed; they are a guide, not a timeout.
 */

const EXTRACT_STEPS = [
  'อ่านหลักฐานทีละช่วงข้อความ เอกสารยาวถูกแบ่งเป็นหลายช่วงที่ซ้อนกันเล็กน้อย',
  'สกัดทักษะจากแต่ละช่วง พร้อมข้อความต้นทางที่อ้างได้ตรงตัว — ทักษะที่อ้างไม่ได้ถูกตัดทิ้ง',
  'จำแนกทักษะเป็นข้อกำหนด / ความต้องการ / ความปรารถนา จากความถี่ข้ามหลักฐานทั้งชุด',
  'แบ่งทักษะตามหมวด K · S · E|C แล้วจัดกลุ่มภายในหมวดเดียวกันเท่านั้น',
]

const COMBINE_STEPS = [
  'เขียนประโยค Need หนึ่งประโยคต่อกลุ่มทักษะ และคำนวณ demand score จากผู้ที่เอ่ยถึง',
  'ตรวจว่า Need ใดขอสิ่งเดียวกัน แล้วรวมเป็น Need เดียว (ต้นฉบับยังเก็บไว้ แยกกลับได้)',
]

export const SKILL_RUN_PLANS: Record<'all' | 'skills' | 'needs', RunPlan> = {
  // Only a legacy `needs_pipeline` row reaches this: new runs are two jobs, a
  // skill_extraction job and then a need_combination job, each with its own plan.
  all: {
    title: 'กำลังสกัดทักษะและรวมเป็น Need (งานแบบเก่าที่ทำทั้งสองขั้นในงานเดียว)',
    steps: [...EXTRACT_STEPS, ...COMBINE_STEPS],
    typical: [60, 300],
  },
  skills: {
    title: 'กำลังสกัดทักษะจากหลักฐาน',
    steps: EXTRACT_STEPS,
    typical: [45, 240],
  },
  needs: {
    title: 'กำลังรวมทักษะเป็น Need',
    steps: COMBINE_STEPS,
    typical: [30, 90],
  },
}

export const PLO_SYNTHESIS_PLAN: RunPlan = {
  title: 'กำลังสังเคราะห์ PLO',
  steps: [
    'เลือก Need หลักไม่เกิน 10 ข้อ เรียงตาม demand score — Need เสริมกลายเป็น PLO เสริม',
    'ร่าง PLO หนึ่งข้อต่อหนึ่ง Need ด้วยกริยา Bloom หนึ่งตัว',
    'ตรวจเกณฑ์ SMART ขั้นพื้นฐานด้วยกฎ: กริยาอยู่ในประโยค ไม่มีคำต้องห้าม ร่องรอยหลักฐานครบ',
    'ผู้ตรวจ SMART ตรวจทีละข้อและสั่งให้แก้ได้ไม่เกิน 3 รอบต่อข้อ',
    'ข้อที่ยังไม่ผ่านถูกเก็บไว้ให้แก้ด้วยมือ ไม่ถูกทิ้ง',
  ],
  typical: [180, 600],
}

/** The same run with the validation agent switched off for this run, or
 *  disabled in `.env`: drafting and the pure-code gate only. */
export const PLO_SYNTHESIS_CODE_ONLY_PLAN: RunPlan = {
  title: 'กำลังสังเคราะห์ PLO (ไม่ใช้ผู้ตรวจ SMART)',
  steps: [
    PLO_SYNTHESIS_PLAN.steps[0],
    PLO_SYNTHESIS_PLAN.steps[1],
    PLO_SYNTHESIS_PLAN.steps[2],
    'ข้อที่ไม่ผ่านกฎพื้นฐานถูกเก็บไว้ให้แก้ด้วยมือ — ไม่มีรอบสั่งแก้จากผู้ตรวจ',
  ],
  typical: [60, 240],
}

export const PLO_REPORT_PLAN: RunPlan = {
  title: 'กำลังสร้างรายงาน PLO',
  steps: [
    'รวบรวม PLO ทั้งชุด แยกข้อหลักกับข้อเสริม',
    'ย้อนรอยแต่ละ PLO ไปยัง Need และหลักฐานต้นทาง',
    'ตรวจจำนวน PLO หลักเทียบช่วง 6–10 ข้อ',
    'ระบุ Need ที่ยังไม่ถูกนำไปเขียนเป็น PLO',
  ],
  typical: [5, 30],
}

/** The set review reads the finished PLOs once; the agent's own loop is bounded
 *  by `plo_review_timeout_seconds` (300s) on the backend, so the usual range
 *  stops well short of it. */
export const PLO_REVIEW_PLAN: RunPlan = {
  title: 'กำลังตรวจคุณภาพชุด PLO',
  steps: ['เตรียมข้อมูลชุด PLO', 'agent ตรวจและเช็กข้อสงสัย', 'สรุปข้อเสนอแนะ'],
  typical: [30, 120],
}
