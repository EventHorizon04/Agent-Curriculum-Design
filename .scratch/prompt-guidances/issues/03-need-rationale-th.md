# 03 — `rationale_th` บน `Need`: schema + ORM + migration

Map: [Review — market_need_synthesis](../market-need-synthesis-review.md)
Type: implementation
Status: open
Blocked by: (none)

## Question

guidance กฎ 12 + Quality Checklist ข้อ 10 สั่งให้ output JSON มี 3 field
(`statement_th` / `statement_en` / `rationale_th`) เหตุผลที่ guidance เขียนไว้เอง:
*"รองรับ Traceability และการอธิบายในวิทยานิพนธ์"*

ปัจจุบัน `_NeedStatement` ประกาศแค่ 2 field และ `models.Need` **ไม่มี** `rationale_th`
เลย (ต่างจาก `PLO` ที่มี)

## งานจริงที่ตามมา

1. field บน `_NeedStatement` (`stages/need_combination.py`)
2. field บน `models.Need`
3. column บน ORM
4. **migration** (Alembic — ห้ามแก้ DB ด้วยมือ)
5. จุดที่ประกอบ `Need` ใน `need_combination` ต้องส่งค่าเข้าไป
6. ที่แสดงผลบน UI — `SkillExtraction.tsx` NeedCard, `PloReport.tsx` การ์ด Need
7. fallback `[ต้องทบทวน]` ต้องเขียน `rationale_th` ว่าอะไร

## ⚠️ กับดักที่ต้องรู้ก่อนเริ่ม

`test_the_prompt_asks_for_the_fields_the_caller_actually_parses` วนเช็กว่า
*ทุก field ของ `_NeedStatement` ปรากฏใน system prompt* — **เป็นการเช็กทางเดียว**

ถ้าเพิ่ม `rationale_th` เข้า **prompt** โดยไม่เพิ่มเข้า `_NeedStatement` test ยังเขียว
และ Pydantic จะทิ้งค่าที่โมเดลเขียนมาเงียบ ๆ = จ่าย token ฟรีโดยไม่มีใครรู้

**เริ่มจาก schema ไม่ใช่จาก prompt** และพิจารณาเพิ่ม test อีกทางด้วย
(field ที่ prompt ขอ ต้องมีใน `_NeedStatement`)

## คำถามที่ต้องตอบก่อนลงมือ

1. **`rationale_th` ต้องสืบกลับหลักฐานไหม** — immutable rule 2 บังคับ trail ของ
   `Need.source_evidence_ids` อยู่แล้ว เหตุผลที่โมเดลเขียนขึ้นเองเป็นข้อความอิสระที่
   **ไม่ถูก validate** ว่าตรงกับหลักฐาน → ต้องระวังไม่ให้มันกลายเป็น trail ที่ดูน่าเชื่อ
   แต่ไม่มีอะไรค้ำ (รูปเดียวกับบั๊ก `source_evidence_ids` ปลอมใน need-based restructure)
2. **แถวเก่าเขียนว่าอะไร** — nullable แล้วปล่อยว่าง หรือ backfill
3. **ยาวแค่ไหน** — ถ้าไม่มีเพดาน มันจะกินพื้นที่การ์ดบน UI และกิน token ของทุก call
