# 03 — scope statement เข้า extract prompt โดยไม่ล้าง cache เก่า

Map: [PLO synthesis ที่ไม่หลุด scope ของหลักสูตร](../map.md)
Type: grilling
Status: resolved
Blocked by: 02 (resolved), 09 (resolved), 13 (resolved)

## Question

scope statement ต้องไปถึง extraction model ให้ได้ โดยโปรแกรมที่ไม่มี scope statement
ต้อง **ไม่ re-extract แม้แต่ window เดียว**

ข้อเท็จจริงที่ทำให้เป็นไปได้: `_EXTRACTION_CONTRACT` = sha256(schema + **system prompt**)
และ system prompt ตอนนี้ static ล้วน — `field_th` / `program_name_th` อยู่ใน **user header
แบบมีเงื่อนไข** และอยู่ใน cache key แยกต่างหาก

ต้องตัดสิน:

1. **ตำแหน่งในข้อความ** — scope statement เข้า user header ต่อจาก `[สาขาวิชา: ...]`
   เป็นบรรทัดใหม่แบบมีเงื่อนไข ใช่ไหม แล้วกติกาข้อ `is_field_relevant` ใน system prompt
   ต้องแก้ถ้อยคำให้อ้างถึง scope statement หรือไม่ — **ถ้าแก้ contract จะขยับและ cache
   ตายทั้งตาราง** ถ้าไม่แก้ model จะรู้ไหมว่าต้องอ่านบรรทัดนั้น
2. **cache key** — ต่อ scope เข้า key แบบไม่มีเงื่อนไขจะเปลี่ยน hash ทุกแถวแม้ scope ว่าง
   (เพราะ separator เพิ่มเข้าไปในสตริงที่ถูก hash). ต่อแบบมีเงื่อนไขเท่านั้นถึงจะได้ key เดิมเป๊ะ
   ยืนยันรูปที่จะใช้ และเขียน test ที่พิสูจน์ว่า key ของโปรแกรมไม่มี scope ไม่ขยับ
   (บทเรียนจาก `test_skill_extraction_cache.py` — ทดสอบด้วยการ replay entry
   ไม่ใช่ assert ราย call site)
3. **`_extraction_contract_fingerprint()`** เรียก `build_extract_skills_prompt` ด้วย
   argument ว่าง — ถ้าเพิ่ม parameter ต้องมั่นใจว่า default ยังทำให้ fingerprint เดิม
   ออกมาเท่าเดิม

**ขอบเขต**: ตัดสินใจอย่างเดียว ผลลงเป็นหัวข้อใน spec ไม่ต้องแก้โค้ด

## เพิ่มหลัง ticket 02 ปิด

[ticket 09](09-graduate-capability-prompt.md) อาจต้องแก้ **system prompt** (กติกาว่าทักษะ
ต้องเป็นสิ่งที่บัณฑิตทำได้) ซึ่งทำให้ `_EXTRACTION_CONTRACT` ขยับและ cache ตายทั้งตาราง —
ตรงข้ามกับ scope statement ที่ไปอยู่ใน user header ได้. ใบนี้ต้องตัดสินทั้งสองอย่างพร้อมกัน
ไม่ใช่แค่ scope statement: ถ้ายังไงก็ต้องยอมให้ contract ขยับหนึ่งครั้ง การพยายามรักษา
cache ไว้สำหรับ scope statement อย่างเดียวก็ไม่มีความหมาย

## เพิ่มหลัง ticket 09 ปิด — โจทย์ของใบนี้เปลี่ยนไปมาก

[ticket 09](09-graduate-capability-prompt.md) ตัดสองข้อสมมติของใบนี้ทิ้ง:

**1. contract ต้องขยับอยู่ดี** — แกนที่สองชนะด้วย **ธงใหม่ในสคีมา**
(`is_graduate_capability`) ซึ่งอยู่ใน `_extraction_contract_fingerprint()` (มัน hash
`model_json_schema()`) → cache ตายทั้งตารางแน่นอน ไม่ว่าจะวาง scope statement ตรงไหน

ทำให้คำถามข้อ 1-3 เดิมของใบนี้ ("จะรักษา cache ไว้ยังไง") **หมดความหมายไปครึ่งหนึ่ง**
สิ่งที่ต้องตัดสินแทนคือ:
- ยอมรับว่า re-extract หนึ่งรอบเป็นราคาของ feature นี้ แล้วทำ**ครั้งเดียว** — รวมทั้ง
  ธงใหม่และ scope statement ใน migration เดียว ไม่ใช่ทยอยแก้ทีละอย่างแล้วจ่ายสองรอบ
- มีทางลด cost ของรอบนั้นไหม (สั่ง prune_cache ล่วงหน้า, warm ทีละโปรแกรม)
- `prune_cache` รายงาน `stale-contract` ได้อยู่แล้ว — ต้องบอก designer ล่วงหน้าไหม
  ว่าการอัปเกรดนี้ทำให้ต้องรันใหม่

**2. scope statement ปนเป็นหลักฐาน** — วางไว้ใน user header ติดข้อความหลักฐาน โมเดลอ่าน
มันเป็นหลักฐานแล้วผลิตทักษะที่ลอกข้อความ scope คำต่อคำ (11 รายการบน ev04/ev05/ev11 ใน
T4_combo; ev04 กับ ev05 ไม่มีคำเหล่านั้นในข้อความเลย → `evidence_span_th` ต้องเป็นของแต่ง
= ชน immutable rule 2)

ต้องตัดสินเพิ่ม:
- **ตำแหน่งใหม่**: อยู่ใน system prompt (ตอนนี้ contract ขยับอยู่แล้ว เลยไม่มีต้นทุนเพิ่ม)
  หรือคงใน user message แต่มีตัวคั่น/ถ้อยคำกำกับชัดว่า "นี่ไม่ใช่หลักฐาน ห้ามสกัดทักษะจาก
  บรรทัดนี้"
- **ยาวได้แค่ไหน** — ปนหนักขึ้นเมื่อ evidence สั้นเทียบ scope. evidence ที่สั้นที่สุดในชุด
  ทดสอบคือ 148 ตัวอักษร ส่วน C_narrow ยาว ~150 → อัตราส่วนราว 1:1 คือจุดที่พัง
- **ทดสอบว่าแก้ได้จริงไหม** — ใบนี้เป็น grilling แต่ข้อนี้อาจต้อง prototype ซ้ำ
  (นับทักษะที่ลอกวลีจาก scope statement เหมือนที่ ticket 09 ทำ) ก่อนจะเชื่อคำตอบ

ยังคงต้องตัดสิน: cache key ของ scope statement (ข้อ 2 เดิม) — แต่ตอนนี้เป็นเรื่องของ
"หลังจาก re-extract รอบใหญ่แล้ว โปรแกรมที่แก้ scope ทีหลังต้อง re-extract เฉพาะตัวเอง"
ไม่ใช่ "รักษาแถวเก่าไว้"

## Answer

**1. scope statement อยู่ใน system prompt** ต่อท้ายบล็อกกติกา ก่อนบรรทัด
`"ตอบเป็น JSON object:"` แบบมีเงื่อนไข (ไม่มี scope = ไม่มีบรรทัดนี้ prompt เดิมเป๊ะ)

[ticket 13](13-scope-position.md) วัดแล้ว: ตำแหน่งนี้ให้ **ชื่อลอกวลีจาก scope = 0**
เทียบกับ 8 ใน user header ขณะที่ recall (4/8) และ false positive (1) **เท่ากันทั้งสอง
ตำแหน่ง** — ย้ายแล้วไม่แลกอะไร. และ contract ขยับอยู่แล้วจากธงใหม่ของ
[ticket 09](09-graduate-capability-prompt.md) จึงไม่มีต้นทุนเพิ่ม

ถ้อยคำที่ทดสอบมาแล้ว — ต้องมีทั้งสองประโยค บรรทัดที่สองไม่ใช่ส่วนเกิน:

```
- ขอบเขตของหลักสูตรนี้: {scope_th}
  ใช้บรรทัดนี้เป็นเกณฑ์ตัดสิน is_field_relevant เท่านั้น ห้ามสกัดทักษะจากบรรทัดนี้
  ทักษะทุกรายการต้องมาจากข้อความ evidence เท่านั้น
```

**2. cache key ต่อ scope แบบไม่มีเงื่อนไข** — `\x00{scope_th}` เสมอ แม้ว่าง

**กลับด้านจากที่ใบนี้ตั้งไว้ตอนแรก**: เหตุผลที่ทำให้ conditional จำเป็นคือ "รักษาแถวเก่า
ให้ยังหยิบได้" ซึ่งหายไปแล้ว — ธงใหม่ในสคีมาทำให้ `_EXTRACTION_CONTRACT` ขยับ ทุกแถว
กลายเป็น miss อยู่ดี ไม่มี key เดิมให้รักษา. conditional จึงเหลือแต่ต้นทุน: branch
ที่ต้องมี test คุ้มตลอดไป แลกกับประโยชน์ครั้งเดียวที่ไม่ได้เกิด

**3. `scope_th` ต้อง _ไม่_ เข้า `_extraction_contract_fingerprint()`**
fingerprint เรียก `build_extract_skills_prompt("", "")` ด้วย argument ว่าง เพิ่ม
parameter `scope_th: str = ""` แบบมีเงื่อนไขแล้ว fingerprint ยังออกมาเท่าเดิม —
**และนั่นคือสิ่งที่ถูกต้อง ไม่ใช่ผลข้างเคียงที่ต้องแก้**

fingerprint คือสัญญาเรื่อง**รูปร่าง**ของ payload ซึ่งไม่แปรตามโปรแกรม; scope statement
เป็น per-program input เหมือน `field_th`/`program_name_th` ที่อยู่ใน cache key แยก
ถ้ามีคนทำให้ scope เข้า fingerprint ทุกโปรแกรมจะมี contract คนละค่า แล้ว
`prune_cache` จะรายงาน `stale-contract` มั่วทั้งตาราง ต้องเขียนกำกับไว้ในโค้ด

**4. re-extract ครั้งเดียวจบ ไม่ prune ล่วงหน้า** — ธงใหม่ + scope + กติกาใหม่
ไปพร้อมกันใน migration เดียว ไม่ทยอยแก้แล้วจ่ายสองรอบ. ไม่สั่ง
`prune_cache --delete` ก่อน deploy เพราะนั่นคือเอา irreversible action มาไว้ก่อนจุด
ที่ยังถอยได้ — ถ้าต้อง rollback แถวเก่ายังใช้ได้ถ้ายังไม่ลบ. `prune_cache` รายงาน
`stale-contract` ได้เองอยู่แล้ว กวาดหลังจากมั่นใจแล้วถูกลำดับกว่า

**5. ไม่เตือนใน UI — log อย่างเดียว** ผู้ใช้จริงคนเดียวคือ designer ที่กดรันใหม่ในโปรแกรม
ตัวเอง เห็นเวลารอเพิ่มครั้งเดียวแล้วจบ. คำเตือนใน UI ต้องรู้ว่า cache ของโปรแกรมนี้ stale
= query `llm_cache` เทียบ contract ก่อนเรนเดอร์หน้า — โครงสร้างใหม่ทั้งชุดเพื่อข้อความ
ที่แสดงครั้งเดียวในชีวิตของ deployment

**6. หลังรอบใหญ่แล้ว โปรแกรมที่แก้ scope ทีหลัง re-extract เฉพาะตัวเอง** — ผลตรงจาก
ข้อ 2: scope อยู่ใน key ไม่ใช่ใน contract โปรแกรมอื่นไม่กระทบ
