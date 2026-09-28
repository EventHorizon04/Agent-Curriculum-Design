/**
 * The policy a Need set is judged against, and the two ways a Need can arrive
 * unwritten. Both mirror Python and neither can be checked across the two
 * languages, so change them together.
 *
 * Bounds: `MIN_NEEDS` and `MAX_CORE_PLOS` in `stages/need_grouping.py`. The
 * floor cannot be enforced by code — too few Needs simply means too few PLOs —
 * so the pipeline logs a policy warning and leaves it to the designer at the
 * checkpoint. That warning went to the server log alone, which is nobody the
 * designer can read: the last real run produced one core PLO against a floor of
 * six and said so only in a terminal.
 *
 * Markers: `_REVIEW_MARKER_TH` and `_PROVIDER_MARKER_TH` in
 * `stages/need_combination.py`. They are two markers rather than one on purpose,
 * and that distinction is the whole reason to surface them — one asks the
 * designer to write the sentence themselves, the other says a call never
 * completed and a re-run is very likely all it takes. Collapsing them is how
 * designers ended up hand-writing Needs a retry would have produced.
 */

/** Mirrors MIN_NEEDS in need_grouping.py. */
export const MIN_CORE_PLOS = 6
/** Mirrors MAX_CORE_PLOS in need_grouping.py. */
export const MAX_CORE_PLOS = 10

/** What a designer has to do about a Need the pipeline could not write. */
export type NeedFallback = 'rewrite' | 'retry'

export const REVIEW_MARKER_TH = '[ต้องทบทวน]'
export const PROVIDER_MARKER_TH = '[เรียกโมเดลไม่สำเร็จ]'

/**
 * Which fallback a Need is, or null for an ordinary one.
 *
 * Read off the start of the statement because that is where need_combination
 * writes it (`f"{marker} {names}"`). Nothing else on the row records it — the
 * fallback is a sentence the pipeline wrote, not a flag it set.
 */
export function fallbackKind(statementTh: string): NeedFallback | null {
  if (statementTh.startsWith(REVIEW_MARKER_TH)) return 'rewrite'
  if (statementTh.startsWith(PROVIDER_MARKER_TH)) return 'retry'
  return null
}

/** The statement without its marker, so the badge is not said twice. */
export function withoutMarker(statementTh: string): string {
  for (const marker of [REVIEW_MARKER_TH, PROVIDER_MARKER_TH]) {
    if (statementTh.startsWith(marker)) return statementTh.slice(marker.length).trim()
  }
  return statementTh
}

export const FALLBACK_LABEL_TH: Record<NeedFallback, string> = {
  rewrite: 'ต้องเขียนเอง',
  retry: 'เรียกโมเดลไม่สำเร็จ',
}

export const FALLBACK_ACTION_TH: Record<NeedFallback, string> = {
  rewrite:
    'ระบบเขียนประโยคนี้ไม่ผ่านเกณฑ์ของตัวเอง สิ่งที่เห็นคือรายชื่อทักษะในกลุ่ม ไม่ใช่ความต้องการ' +
    ' — ต้องเขียนประโยคใหม่เอง รันซ้ำไม่ช่วย',
  retry:
    'การเรียกโมเดลไม่สำเร็จ ไม่ใช่ว่าเนื้อหามีปัญหา — กด Re-run Need ก่อน แล้วค่อยดูว่ายังเหลือไหม',
}
