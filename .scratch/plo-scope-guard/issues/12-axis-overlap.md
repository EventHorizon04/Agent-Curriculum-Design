# 12 — noise ที่สองแกนพลาด ทับกันแค่ไหน

Map: [PLO synthesis ที่ไม่หลุด scope ของหลักสูตร](../map.md)
Type: prototype
Status: resolved
Blocked by: 09 (resolved)

## Question

[ticket 11](11-two-axis-selection.md) ต้องเลือกว่าสองแกนรวมกันด้วย `and` หรือ `or`
แต่ตัวเลขที่มีตอนนี้เป็น recall **รายแกน** (~50% และ 56%) ซึ่งไม่บอกอะไรเลยว่าควรรวมยังไง:

- ถ้าสองแกนพลาด **ใบเดียวกัน** → `or` แทบไม่เพิ่มอะไร และ `and` กรองแรงเกินโดยไม่ได้อะไรคืน
- ถ้าพลาด **คนละใบ** → `or` ดันเพดานขึ้นได้จริง ส่วน `and` จะกรองได้แค่ส่วนที่ทับกัน

**วัดได้จากข้อมูลที่มีอยู่แล้ว ไม่ต้องเรียก LLM ใหม่**: `_Base` ของ prototype 09 มี
`is_field_relevant` อยู่ในสคีมาด้วย เลยเก็บ**ทั้งสองธงจากการรันเดียว** (`proto09_results.json`
field `relevant` และ `graduate`) — treatment `T2_field` จึงเป็นชุดข้อมูลที่วัด overlap
ได้ตรง ๆ โดยไม่ต้องจับคู่ชื่อทักษะข้ามการรัน

**ข้อจำกัดที่ต้องบันทึก**: `T2_field` รันโดย**ไม่มี scope statement** — `is_field_relevant`
ตัดสินจาก `field_th` ใน user header เท่านั้น (พฤติกรรมของระบบปัจจุบัน) ไม่ใช่จาก scope
statement ที่ ticket 02 ออกแบบ. overlap ที่ได้จึงเป็น **baseline ก่อนมี scope statement**

ต้องได้:

1. ตาราง 2×2 ของทักษะบน NOISE (ev10, ev11): field-OFF เท่านั้น / grad-OFF เท่านั้น /
   OFF ทั้งคู่ / ไม่ติดธงเลย
2. recall และ false positive ของกฎรวมสามแบบ — `field only`, `grad only`, `or`, `and` —
   บน NOISE และบน CORE (ev06-09, ev14)
3. ตัวเลขเดียวกันจากฝั่งที่มี scope statement เท่าที่เทียบได้ (`C_narrow` ใน
   `proto02_results_ollama.json` มีเฉพาะ `relevant`) — เทียบที่ระดับ evidence

**ขอบเขต**: วัดอย่างเดียว ผลเป็น input ของ [ticket 11](11-two-axis-selection.md)

## Answer

**ทับกัน 100% — ไม่มีทักษะแม้แต่ตัวเดียวที่ติดธงแกนเดียว**

| กลุ่ม | OFF ทั้งสองแกน | field เท่านั้น | grad เท่านั้น | ไม่ติดธง |
|---|---|---|---|---|
| NOISE (ev10, ev11) | 5 | **0** | **0** | 4 |
| CORE (ev06-09, ev14) | 1 | **0** | **0** | 28 |

`field only` / `grad only` / `or` / `and` จึงให้ตัวเลขเท่ากันหมด (NOISE 5/9 = 56%,
CORE 1/29 = 3%) — **`and` กับ `or` แยกไม่ออกจากข้อมูลนี้**

**และสิ่งที่ใหญ่กว่าคำถามเดิม**: แกนที่สองไม่ได้เพิ่มมิติ มันไปขยับธงสาขา.
`T2_field` ไม่มี scope statement เปลี่ยนแค่การเพิ่มช่อง `is_graduate_capability`
พร้อมคำอธิบาย แล้วธง `is_field_relevant` ขยับจาก **3/9 (`A_none`) เป็น 5/9** เอง
และตรงกับธงบัณฑิตทุกตัว — การอธิบายว่า "สมรรถนะบัณฑิต vs กิจกรรมของสถาบัน" ทำให้โมเดล
เข้าใจ**คำถามเดิม**คมขึ้น แล้วตอบสองช่องด้วยคำตัดสินเดียว

ผลเต็มพร้อมข้อจำกัด: [`research/12-overlap-findings.md`](../research/12-overlap-findings.md)
