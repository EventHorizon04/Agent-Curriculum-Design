/**
 * What `demand_score` is, in one place.
 *
 * The number is rendered on four pages and, until this module existed, only one
 * of them explained it — with a sentence describing a formula the scorer had
 * stopped using: "สัดส่วนน้ำหนักของหลักฐานที่กล่าวถึงความต้องการนี้", which is the
 * single pooled frequency block the score had before it was split. The figure on
 * screen was right and the explanation beside it was wrong, which is worse than
 * no explanation: a designer reads the ranking as "how many people said it" and
 * cannot see why the capability three employers named outranks the one nine
 * documents mention in passing.
 *
 * The weights mirror `stages/demand.py` (MANDATE_WEIGHT / PRACTITIONER_WEIGHT /
 * OTHER_VOICE_WEIGHT). No test spans the two languages, so change them together
 * — and read that module's comment first: the split exists because a pooled
 * denominator inverts the ranking, and the two frequency blocks each divide by
 * their own audience so that adding applicant interviews cannot dilute what the
 * employers said.
 */

export const MANDATE_WEIGHT = 0.2
export const PRACTITIONER_WEIGHT = 0.55
export const OTHER_VOICE_WEIGHT = 0.25

/** The short label beside the number. */
export const DEMAND_LABEL_TH = 'Demand'

/**
 * The full account, for a `title`. Long for a tooltip on purpose: the thing a
 * designer needs is which voices the score counts, and naming the practitioner
 * types is the only way that question gets answered without leaving the page.
 */
export const DEMAND_SCORE_TITLE_TH =
  'คะแนนความต้องการ = สภาวิชาชีพระบุหรือไม่ 20%' +
  ' + สัดส่วนเสียงผู้ปฏิบัติงานที่ระบุ 55% (สภาวิชาชีพ นายจ้าง อุตสาหกรรม ศิษย์เก่า ผู้เชี่ยวชาญ)' +
  ' + สัดส่วนเสียงอื่นที่ระบุ 25% — สองก้อนหลังหารด้วยจำนวนเสียงในกลุ่มของตัวเอง' +
  ' ไม่ใช่ทั้งคลัง เสียงกลุ่มหนึ่งจึงเจือจางอีกกลุ่มไม่ได้'

/** The number as it is shown. One formatter so four pages cannot round differently. */
export function demandPercent(score: number): string {
  return `${(score * 100).toFixed(0)}%`
}
