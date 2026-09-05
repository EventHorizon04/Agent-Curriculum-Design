# 13 — scope statement ใน system prompt ยังปนเป็นหลักฐานไหม

Map: [PLO synthesis ที่ไม่หลุด scope ของหลักสูตร](../map.md)
Type: prototype
Status: resolved
Blocked by: 09 (resolved)

## Question

[ticket 03](03-extraction-prompt-and-cache.md) เลือกวาง scope statement ไว้ใน
**system prompt** ต่อท้ายบล็อกกติกา ก่อนบรรทัด `"ตอบเป็น JSON object:"` เพื่อแก้บั๊ก
ที่ [ticket 09](09-graduate-capability-prompt.md) เจอ — scope ใน user message ติด
ข้อความหลักฐานถูกอ่านเป็นหลักฐาน (11 ทักษะลอกวลี scope บน evidence ที่ไม่มีคำเหล่านั้นเลย
→ `evidence_span_th` เป็นของแต่ง = ชน immutable rule 2)

หลักฐานที่มีสนับสนุนได้แค่บางส่วน: `T1`/`T2`/`T3` ใส่**กติกา**ใหม่ใน system prompt
แล้วได้ contamination 0 — แต่ยังไม่เคยทดสอบ scope statement ที่**มีชื่อทักษะอยู่ในตัวมันเอง**
("การแปลเอกสารธุรกิจและกฎหมายจีน-ไทย") ซึ่งเป็นตัวล่อคนละแบบกับกติกา

ทั้ง spec แขวนอยู่บนสมมติฐานนี้ ถ้า system prompt ยังปนต้องคิดตำแหน่งใหม่หมด

## การทดลอง

`C_narrow` ตัวเดิมจาก [ticket 02](02-scope-statement-shape.md) สองตำแหน่ง สคีมามีธง
ทั้งสองแกนตามที่ [ticket 11](11-two-axis-selection.md) ตัดสิน — เทียบ**ตำแหน่งล้วน ๆ**

| variant | scope อยู่ที่ | คาดหมาย |
|---|---|---|
| `U_user` | user header หลัง `[สาขาวิชา: ...]` | ปน (ทราบแล้วจาก ticket 02/09) |
| `S_system` | system prompt ก่อน `"ตอบเป็น JSON object:"` | ต้องไม่ปน |

วัด: จำนวนทักษะที่ชื่อลอกวลีจาก scope statement, recall บน NOISE (ev10/ev11),
false positive บน CORE (ev06-09, ev14) — เทียบกับตัวเลขที่มีอยู่แล้ว

**ขอบเขต**: วัดอย่างเดียว ผลเป็น input ของ [ticket 03](03-extraction-prompt-and-cache.md)

## Answer

**ย้ายไป system prompt แก้ได้จริง และไม่แลกอะไรเลย** — 28/28 call, 0 error

| | `U_user` | `S_system` |
|---|---|---|
| ชื่อลอกวลีจาก scope statement | **8** | **0** |
| `evidence_span_th` หาไม่พบในหลักฐาน | **9** | **3** |
| NOISE ติดธง (recall) | 4/8 | 4/8 |
| CORE ติดธง (FP) | 1/27 | 1/26 |

recall กับ false positive เท่ากันทั้งสองตำแหน่ง — การย้ายไม่มีต้นทุนด้านคุณภาพ

`U_user` ทำซ้ำบั๊กของ ticket 09 ได้เป๊ะบน `ev04`/`ev05` (สอง evidence ที่สั้นที่สุด):
สี่ทักษะที่ทั้งชื่อและ span ลอกจาก scope statement คำต่อคำ — **span คัดลอกตรงตัวจริง
แต่คัดจาก scope ไม่ใช่จากหลักฐาน** ซึ่งเป็นรูปที่อันตรายที่สุด เพราะวันที่ scope
บังเอิญมีวลีตรงกับหลักฐาน `is_grounded()` จะปล่อยผ่าน

span ที่หาไม่พบ 3 รายการของ `S_system` ไม่มีตัวไหนมาจาก scope — เป็น span ที่โมเดล
ตัดกลางประโยคหรือเรียบเรียงใหม่ ซึ่งเกิดในทุก variant มาตั้งแต่ต้นและ `is_grounded()`
จับได้อยู่แล้ว

ผลเต็มพร้อมข้อจำกัด: [`research/13-position-findings.md`](../research/13-position-findings.md)
