# 04 — ธงสองแกนขึ้นถึงระดับ Need ยังไง

Map: [PLO synthesis ที่ไม่หลุด scope ของหลักสูตร](../map.md)
Type: grilling
Status: resolved
Blocked by: 02 (resolved), 09 (resolved)

> รวมจาก ticket 04 (แกน "อยู่ในสาขาไหม") และ [ticket 10](10-graduate-axis-signal.md)
> (แกน "บัณฑิตทำได้ไหม") — คำถามเดียวกันคนละแกน ตัดสินแยกกันจะได้คำตอบไม่เข้าชุด

## Question

สองแกนที่ ticket 02 และ [ticket 09](09-graduate-capability-prompt.md) พิสูจน์มาแล้ว
อยู่บน `ExtractedSkill` เป็นธงรายทักษะ. ใบนี้ตัดสินว่ามันขึ้นถึง `Need` ยังไง —
รูปที่เก็บ ที่ที่คำนวณ กฎรวม และ migration

ตกลงไว้แล้วสำหรับแกน "อยู่ในสาขา": **สมาชิก in-field อย่างน้อย 1 คน → Need อยู่ในสาขา**
(ภาพสะท้อนของกฎ `or` ที่ `skill_extraction.py:238` ยกขึ้นมาอีกชั้น)

ต้องตัดสิน:

1. **รูปบน `ExtractedSkill`** — `is_graduate_capability: bool = True` แยกเป็น field ใหม่
   คู่ขนานกับ `is_field_relevant` หรือยุบสองแกนเป็น field เดียวหลายค่า?
   สองแกนไม่ทับกัน ("การสร้างเครือข่ายความร่วมมือระดับสากล" in-field แต่ไม่ใช่สมรรถนะบัณฑิต)
   → ยุบแล้วเสียข้อมูล แต่ต้องเขียนเหตุผลไว้ ไม่งั้นคนถัดไปยุบ
2. **รูปบน `Need`** — bool ต่อแกน หรือ counter (เทียบ precedent `classification_coverage:
   dict[str, int]`)? counter บอก designer ได้ว่า "3 ใน 8 skill อยู่ในสาขา" ซึ่ง
   [ticket 06](06-checkpoint-two-buckets.md) น่าจะอยากใช้ แต่ selection ใช้แค่ bool
3. **store หรือ derive** — คำนวณที่ `need_combination` ตอนสร้าง group (มี members
   อยู่ในมือแล้ว `need_combination.py:202`) แล้วเก็บลงคอลัมน์ หรือ derive ตอน read
   จาก member skills? เทียบ precedent สองทาง: `classification_coverage` /
   `stakeholder_coverage` **store**, ส่วน `cited_need_ids` **derive โดยเจตนา**
4. **กฎรวม** — แกน "บัณฑิตทำได้" ใช้กฎ any เหมือนแกนสาขา หรือเข้มกว่า?
   ต่างกันตรงที่ทักษะฝั่งสถาบันมักมาเป็นกลุ่มก้อนจาก evidence เดียว
5. **`classification` เกี่ยวไหม** — `is_optional_group()` นับ `unclassified` เป็นกลาง
   ทั้งสองฝั่งโดยเจตนา. กฎ "requirement wins" ทับ `unclassified` ไปแล้ว (ทักษะนอกสาขา
   ที่สภาวิชาชีพ/วิสัยทัศน์พูดถึง ออกมาเป็น `requirement`) — วิสัยทัศน์สถาบันเป็นแหล่งของ
   ทั้ง theme D (มนุษย์เก็บ) และ "การบริหารจัดการแหล่งรายได้" (มนุษย์ทิ้ง) →
   สองแกนใหม่ต้องทำงานได้แม้ classification เป็น `requirement`. ยืนยันว่าไม่มีที่ไหน
   ให้ `requirement` ข้ามแกนใหม่ไปได้ และเขียนเหตุผลลง spec เพื่อไม่ให้คนถัดไปยุบรวม
6. **ตัดที่ระดับ stakeholder ไม่ได้ — ยืนยันและเขียนเหตุผลลง spec**
   เฉลยมนุษย์เก็บ Need ของผู้บริหาร (9 → theme B+D), อ.ผู้รับผิดชอบ (10 → D),
   อ.ผู้สอน (11 → A) ไว้ครบ ตัดเฉพาะ *เนื้อหาบางส่วน* ในสิ่งที่เขาพูด
   → กฎแบบ "`administrator` กับ `program_committee` เป็น evidence ที่ไม่เข้าสู่ PLO"
   ผิดชัดเจน ต้องกันไม่ให้ใครใส่กลับเพราะมันเขียนง่ายกว่า
7. **migration** — คอลัมน์ใหม่บน `skills` (แกนที่สอง) และบน `needs` (ถ้าข้อ 3 ให้ store)
   ค่า default ของแถวเก่าต้องรักษาพฤติกรรมเดิม: "อยู่ในสาขา" และ "เป็นสมรรถนะบัณฑิต"
   (โปรแกรมไม่มี scope statement = ไม่กรองอะไรเลย)

**ขอบเขต**: ตัดสินใจอย่างเดียว ผลลงเป็นหัวข้อใน spec

## Answer

**รูปที่ตกลง**

| ชั้น | เก็บอะไร | ชนิด |
|---|---|---|
| `ExtractedSkill` | `is_field_relevant` (มีอยู่แล้ว) | `bool = True` |
| `ExtractedSkill` | `is_graduate_capability` (**ใหม่**) | `bool = True` |
| `Need` | `in_field_skill_count` (**ใหม่**) | `int`, store |
| `Need` | `graduate_capability_skill_count` (**ใหม่**) | `int`, store |
| `Need` | `is_field_relevant` / `is_graduate_capability` | `@property` = `count > 0` |

**1. สองแกนแยกกันบน `ExtractedSkill` ไม่ยุบเป็น enum เดียว** — สองแกนไม่ทับกัน
("การสร้างเครือข่ายความร่วมมือระดับสากล" in-field แต่ไม่ใช่สมรรถนะบัณฑิต) enum เดียว
ต้องมีค่า `both_off` และบังคับให้โมเดลเลือกค่าเดียวจากสี่ ซึ่ง**ไม่ใช่รูปที่ ticket 09
วัดได้ 56%** — ที่วัดคือ bool แยก. ยุบทีหลังได้ แยกทีหลังไม่ได้

**2. บน `Need` เป็น counter ไม่ใช่ bool** — bool derive จาก counter ได้ ย้อนกลับไม่ได้
และ [ticket 06](06-checkpoint-two-buckets.md) ต้องบอก designer ว่า "3 ใน 8" ไม่ใช่แค่ "อยู่".
เลือก `int` ไม่ใช่ `dict` แบบ `classification_coverage` เพราะแกนมีสองค่าและตัวหาร
(`len(member_skill_ids)`) อยู่บน Need แล้ว — dict จะเก็บข้อมูลซ้ำ

**3. store ไม่ derive** — precedent ที่ใกล้กว่าคือ `classification_coverage` /
`stakeholder_coverage` ซึ่ง store ทั้งคู่และคำนวณจาก members ชุดเดียวกันที่
`need_combination.py:202`. `cited_need_ids` derive เพราะเป็นความสัมพันธ์ PLO→Need
ที่เปลี่ยนทุกครั้งที่ลบ PLO — ธงสองแกนไม่เปลี่ยนหลัง group ถูกสร้าง (re-extract สร้าง
Need ใหม่อยู่ดี). derive ยังบังคับให้ทุกหน้าจอที่โชว์ Need ต้อง join `skills` กลับ

**4. กฎ any ทั้งสองแกน อยู่บน model ที่เดียว** — `@property` = `count > 0` ไม่ใช่ปล่อยให้
ticket 05 กับ 06 เขียน `count > 0` คนละที่แล้ว drift. **ไม่ใช้ majority กับแกนสถาบัน**:
prototype 09 วัด false positive 1/29 แต่ recall 56% → ธงที่ติดมาเชื่อได้ แต่ที่ไม่ติด
พลาดครึ่งหนึ่ง. any คือฝั่งปล่อยผ่าน ตรงกับนโยบาย "ห้ามตัดทิ้งเอง"; majority บนสัญญาณ
ที่ recall แค่ครึ่งคือการตัดของถูกทิ้ง

**5. สองแกนอยู่นอก `classification` ทั้งคู่ — precedence 5 ข้อไม่ขยับ**
เหตุผลที่ต้องปักไว้: `requirement wins` จะทับกฎใหม่**ตรงจุดที่ต้องการมันที่สุด**.
"การบริหารจัดการและพัฒนาแหล่งรายได้" มาจากวิสัยทัศน์สถาบัน → evidence เป็น `requirement`
→ `classification` เป็น `requirement` เสมอ ต่อให้ธงบอกว่าไม่ใช่สมรรถนะบัณฑิต. กฎแบบ
`is_graduate_capability=False → unclassified` จึงเป็น dead rule บนตัวอย่างที่มันควรจับ
พอดี — เหมือนที่แกนสาขาเจอมาแล้ว. selection ([ticket 05](05-synthesis-selection-filter.md))
ต้องอ่านธงตรง ๆ ไม่ผ่าน `classification`

**6. migration: backfill ไม่ใช่ default 0**
- `skills.is_graduate_capability` — `server_default true` เหมือน `is_field_relevant`
- `needs.*_count` — backfill `jsonb_array_length(member_skill_ids)` (`member_skill_ids`
  เป็น JSONB ตั้งแต่ `aa1e44fd1a46`) ทำได้ใน `UPDATE` เดียว
- `server_default 0` ผิด: Need เก่าทุกแถวจะอ่านได้ว่า "ไม่มีสมาชิกไหนอยู่ในสาขา" =
  เปลี่ยนพฤติกรรมของโปรแกรมที่มีอยู่โดยไม่มีใครสั่ง
- `nullable` ("ไม่เคยประเมิน") ซื่อสัตย์กว่าแต่บังคับ tri-state ให้ทุกผู้บริโภค และ
  `skills.is_field_relevant` ก็ default `True` ด้วยเหตุผลเดียวกันมาแล้ว

**7. ห้ามตัดที่ระดับ stakeholder — ข้อห้าม ไม่ใช่ "ไม่ได้ทำ"**
เฉลยมนุษย์ (`Needs_to_PLO_TCISM.xlsx`) เก็บ Need ของผู้บริหาร (→ theme B+D),
อ.ผู้รับผิดชอบ (→ D), อ.ผู้สอน (→ A) ไว้ครบ ตัดเฉพาะ*เนื้อหาบางส่วน*ที่เขาพูด.
กฎ "`administrator`/`program_committee` ไม่เข้าสู่ PLO" เขียนง่ายกว่าและดูถูกเสมอ
ในสายตาคนที่ไม่ได้อ่านเฉลย — spec ต้องมีเหตุผลปักไว้กันคนใส่กลับ

**8. `Need` ใช้ชื่อเดียวกับ `ExtractedSkill`** — precedent อยู่ในโมเดลเดียวกัน:
`ksec_category` และ `bloom_level` อยู่ทั้งสองชั้น ชื่อเดียวกัน โดย Need เป็นค่าที่รวมขึ้นมา
(`resolve_need_ksec`, `merge_bloom`). ชื่อแบบ `has_in_field_skill` ตั้งตาม*วิธีคำนวณ*
ไม่ใช่ตาม*ความหมาย* — ถ้า [ticket 07](07-eval-protocol.md) สั่งเปลี่ยน threshold
ชื่อจะโกหกทันที

**9. counter นับธงดิบรายแถว ไม่ผ่าน or-by-name**
โค้ดมีความไม่สม่ำเสมออยู่แล้ว: `classification` ผ่าน `class_by_norm` (or-by-name,
`skill_extraction.py:238`) แต่ `is_field_relevant` เขียนลงแถวแบบดิบ (`:541`) —
ชื่อเดียวกันสองแถวมีธงต่างกันได้. **ไม่แก้**: property `count > 0` ให้ผลเท่ากันทั้งสองทาง
(or-by-name คือ any ในกลุ่มย่อย) ต่างกันแค่เศษส่วนที่ designer อ่าน และ or-by-name
จะดัน counter เข้าใกล้ total เสมอเมื่อชื่อซ้ำเยอะ = สัญญาณจืดจนไร้ประโยชน์กับ ticket 06.
spec ต้องเขียนให้ชัดว่าตัวเลขนี้คือ**จำนวนแถว** ไม่ใช่จำนวนทักษะที่ต่างกัน

## ตกไปข้างหน้า

- [ticket 05](05-synthesis-selection-filter.md) ได้ input ครบแล้ว: อ่าน property สองตัว
  ตรง ๆ ไม่ผ่าน `classification`
- [ticket 06](06-checkpoint-two-buckets.md) ได้ตัวเลขเศษส่วนไปโชว์
- [ticket 11](11-two-axis-selection.md) ตัดสินว่าสองแกนรวมกันยังไงตอนเลือก
  (`and` / `or` / น้ำหนัก) — ใบนี้ให้แค่ธงรายแกน
