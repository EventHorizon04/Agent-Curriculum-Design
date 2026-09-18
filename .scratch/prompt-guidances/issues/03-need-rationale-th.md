# 03 — `rationale_th` บน `Need`: schema + ORM + migration

Map: [Review — market_need_synthesis](../market-need-synthesis-review.md)
Type: implementation
Status: resolved
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


---

## คำตัดสิน — 2026-09-18: **ทำเฉพาะ `Need.rationale_th`** · backfill · มีเพดาน

อีกสองตัว (`ClusterAssignment.rationale_th`, `merge_rationale_th`) **ไม่ทำในรอบนี้** —
ทั้งคู่อยู่ใน schema ที่ `_CLUSTERING_CONTRACT` hash และควรตัดสินหลังรู้ผลการทดลอง
`label_th` (ถ้าชื่อกลุ่มไม่มีผลต่อคุณภาพ partition ทั้ง label และ rationale ควร **ออก**
จาก schema แทนที่จะเพิ่มเข้าไป)

### สิ่งที่ลงไปแล้ว

| จุด | ที่ |
|---|---|
| field บน `_NeedStatement` + validator | `stages/need_combination.py` |
| field บน `models.Need` (default `""`) | `models.py` |
| column `NOT NULL server_default ''` | `data/orm.py` |
| migration + backfill | `migrations/versions/c7e2f81a4b93_need_rationale.py` |
| prompt ขอ field + ระบุเพดาน | `prompts/summarize_need.py` |
| fallback `[ต้องทบทวน]` เขียนว่าไม่มีเหตุผล | `need_combination.py` |
| UI 2 จุด | `components/NeedCard.tsx` · `PloReport.tsx` (การ์ด TraceNeed) |

### เพดาน — `MIN_RATIONALE_CHARS = 20` / `MAX_RATIONALE_CHARS = 240`

อยู่ใน `prompts/summarize_need.py` ข้าง `MIN_STATEMENT_CHARS` ด้วยเหตุผลเดียวกัน:
ตัวเลขที่ prompt บอกกับตัวเลขที่ validator ใช้ปฏิเสธ ต้องเป็นตัวเดียวกัน
มี test ยืนยันว่า prompt พิมพ์ช่วงเดียวกับที่ validator บังคับ

เพดานบนไม่ใช่เรื่องความสวยงาม — field นี้ติดไปกับทุกแถว Need แสดงในการ์ด และเป็นที่เดียว
ใน response ที่โมเดลใช้ token ได้ไม่จำกัดโดยไม่มีกฎอื่นดันกลับ

### backfill — เขียนเฉพาะสิ่งที่แถวรู้อยู่แล้ว

```sql
'[สร้างย้อนหลัง] Need นี้รวมจากทักษะ ' || jsonb_array_length(member_skill_ids)
|| ' รายการในหมวด ' || ksec_category || ' — ระบบยังไม่ได้เก็บเหตุผลตอนที่สร้าง'
WHERE rationale_th = ''
```

**ไม่ join `skills`** โดยเจตนา — การเอาชื่อทักษะสมาชิกมาประกอบเป็น "เหตุผล" คือการวาง
คำอธิบายที่ไม่มีโมเดลไหนเคยให้ ไว้ในช่องที่คนอ่านจะถือว่าเป็นเหตุผลของ Need นั้น
รูปเดียวกับ trail ที่ผ่าน validator แล้วโกหก · `WHERE` ทำให้รันซ้ำไม่ทับของจริง
มี test ยืนยันทั้งสองข้อ

### เส้นแบ่งที่ต้องไม่หาย

`rationale_th` = **คำอธิบายของโมเดล** · `source_evidence_ids` = **trail** ที่ immutable
rule 2 พูดถึง และประกอบด้วยโค้ด

- prompt ห้ามอ้างหลักฐานหรือแหล่งที่มานอกรายชื่อทักษะที่ให้มา
- UI ทั้งสองจุดติดป้าย "คำอธิบายของโมเดล" และ**อยู่นอกแผง "ดูที่มา"** ซึ่งเป็น trail
- validator ปฏิเสธคำตอบว่าง ๆ ด้วย `find_vague_phrase` ตัวเดียวกับที่ statement ใช้ —
  กฎเดียว สแกนเดียว ไม่ใช่สองชุดคำที่จะเถียงกันทีหลัง

### กับดักที่ใบนี้เตือนไว้ — ปิดแล้ว

`test_the_prompt_asks_for_the_fields_the_caller_actually_parses` เช็กทางเดียว
ตอนนี้มี `test_the_prompt_asks_for_no_field_the_caller_cannot_parse` เป็นอีกทาง
พร้อม `test_the_field_detector_would_actually_catch_one` ที่ทดสอบตัวตรวจเอง
(guard ทางเดียวที่อ่านไม่เจออะไรเลย คือความล้มเหลวแบบเดียวกับที่มันมีไว้จับ)
