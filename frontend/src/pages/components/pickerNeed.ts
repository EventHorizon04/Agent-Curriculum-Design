import { FALLBACK_LABEL_TH, MAX_MERGE_NEEDS, fallbackKind } from '../../constants/needPolicy'

export interface PickerNeed {
  need_id: string
  statement_th: string
  demand_score?: number
}

/** Short Thai reason a Need cannot be drafted from, or null when it can. The
 *  server answers 422 for these; saying so up front saves the round trip. */
export function unwrittenReason(n: PickerNeed): string | null {
  const kind = fallbackKind(n.statement_th)
  return kind ? `ยังไม่มีประโยค Need (${FALLBACK_LABEL_TH[kind]})` : null
}

/** The Needs no outcome cites, most demanded first (server order when the list
 *  carries no demand). One rule for the picker's first group and the attach list. */
export function unusedNeedsOf(needs: PickerNeed[], citedIds: Set<string>): PickerNeed[] {
  return needs
    .filter((n) => !citedIds.has(n.need_id))
    .sort((a, b) => (b.demand_score ?? 0) - (a.demand_score ?? 0))
}

/** Why "เพิ่ม Need" is off for an outcome, or null when it can be used. */
export function attachBlockedReason(citedCount: number, unused: PickerNeed[]): string | null {
  if (citedCount >= MAX_MERGE_NEEDS) return `PLO นี้มี Need ครบ ${MAX_MERGE_NEEDS} ข้อแล้ว`
  if (unused.every((n) => unwrittenReason(n))) return 'ไม่มี Need ที่ยังไม่มี PLO'
  return null
}
