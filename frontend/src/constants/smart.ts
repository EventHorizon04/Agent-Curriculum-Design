import type { SMARTCheck, ValidatedBy } from '../types/plo'

/**
 * Thai wording for the SMART verdict, in one place.
 *
 * The finding labels mirror `smart_vocabulary.FINDING_LABEL_TH` in Python. Both
 * exist because the exporter renders the same codes into an Excel workbook a
 * designer sends to MHESI, and a drift test cannot span the two languages —
 * so change them together.
 *
 * The map they replace had been stale for months: it carried S_object, A_level
 * and a long-dead `R_alignment`, while the backend emitted five codes. Three of
 * them fell through to raw English on both pages, and the copy of the map in
 * each page meant fixing one fixed nothing.
 */

export const SMART_KEYS: (keyof SMARTCheck)[] = [
  'specific',
  'measurable',
  'achievable',
  'relevant',
  'timely',
]

export const SMART_LABEL_TH: Record<string, string> = {
  specific: 'Specific',
  measurable: 'Measurable',
  achievable: 'Achievable',
  relevant: 'Relevant',
  timely: 'Time-bound',
}

export const FINDING_LABEL_TH: Record<string, string> = {
  // hard — pure code decides these, and they are the only things that escalate
  S_verb: 'ประโยคไม่ได้ขึ้นต้นด้วยกริยาที่ประกาศไว้',
  S_multi_verb: 'ประกาศกริยาเกินหนึ่งตัว หรือสองตัวที่ระดับ Bloom ห่างกัน',
  M_forbidden: 'ใช้คำที่วัดผลไม่ได้',
  R_evidence: 'ร่องรอยหลักฐานไม่ครบหรืออ้างถึง Need ที่ไม่มีอยู่',
  // soft — the validator judges these, and none of them block
  S_object: 'กรรมของกริยากว้างเกินไป',
  M_assessable: 'ไม่ชัดว่าประเมินด้วยเครื่องมือใด',
  A_level: 'ระดับ Bloom ไม่สมเหตุสมผลกับระดับคุณวุฒิ',
  A_actor: 'ผู้กระทำไม่ใช่บัณฑิต แต่เป็นสถาบัน องค์กร หรือหลักสูตร',
  A_scope: 'เป็นงานของวิชาชีพอื่น อยู่นอกขอบเขตของหลักสูตร',
  R_needs: 'ยังไม่ตอบ Need ที่อ้างถึง',
  T_horizon: 'กรอบเวลาขัดกับการสำเร็จหลักสูตร',
}

export function findingLabel(code: string): string {
  return FINDING_LABEL_TH[code] ?? code
}

/** What each provenance value means to a designer, and how it should read. */
export const VALIDATED_BY_TH: Record<ValidatedBy, string> = {
  agent: 'ตรวจด้วยผู้ตรวจ SMART แล้ว',
  // Three causes share this value (skipped this run, disabled in .env, endpoint
  // failed); `smart_diagnosis_th` says which, so this line must not pick one.
  code_only: 'ตรวจด้วยกฎพื้นฐานเท่านั้น — ไม่ได้ผ่านผู้ตรวจ SMART',
  stale: 'แก้ข้อความแล้ว ยังไม่ได้ตรวจซ้ำ',
  legacy: 'ตรวจก่อนมีผู้ตรวจ SMART',
}

/** Rows that need the designer's attention before the set is submitted. */
export function needsAttention(validatedBy: ValidatedBy): boolean {
  return validatedBy === 'stale' || validatedBy === 'code_only'
}
