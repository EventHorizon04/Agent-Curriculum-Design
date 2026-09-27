# 17 — retry ของ `_NeedStatement` จ่ายสามเท่าแล้วได้คำตอบเดิมตัวต่อตัว

Map: [PLO synthesis ที่ไม่หลุด scope ของหลักสูตร](../map.md)
Type: bug / grilling
Status: open
Blocked by: (none)
Related: [ใบ 15](15-no-core-plos-on-the-real-run.md) (Need fallback `[ต้องทบทวน]` ที่หลุดเป็น PLO)

## สิ่งที่เห็น (รัน 2026-09-27 · typhoon-v2.5-30b-a3b-instruct)

กลุ่ม `การรักษาผลประโยชน์ของบริษัทผ่านภาษาจีนธุรกิจ` ตก `looks_like_a_skill_list`
สามครั้งติด แล้วจบที่ fallback `[ต้องทบทวน]` ซึ่งกลายเป็น PLO จริงในรันนั้น

**ทั้งสามครั้งคืนข้อความเดียวกันตัวอักษรต่อตัวอักษร** — ไม่ใช่คำตอบใกล้เคียง แต่เหมือนกันเป๊ะ
ทั้ง `statement_th`, `statement_en` และ `rationale_th`

ขณะที่ prompt โตขึ้นทุกครั้ง เพราะ Instructor แนบความพยายามที่ล้มเหลวกับ error กลับเข้าไป:

```
attempt 1   2,207 prompt_tokens
attempt 2   5,444          (+3,237)
attempt 3  10,340          (+4,896)     รวม ~18,000 token
```

`_STATEMENT_ATTEMPTS = 3` → **จ่าย token สามเท่าเพื่อคำตอบเดียว** แล้วจบด้วย fallback เหมือนกับ
ที่ไม่ retry เลย

## ข้อเท็จจริงเชิงโค้ด

`llm._complete` ส่ง `**kwargs` ผ่านตรง ๆ ไม่ตั้ง `temperature` ให้เอง · ที่ตั้งจริงมีสามจุด
และ**ไม่มีจุดไหนเป็น slot ของ typhoon**:

| จุด | ค่า |
|---|---|
| `llm_clustering.py:170` `:195` | `temperature=0` |
| `smart_agent.py:425` | `temperature=0` |
| `need_combination.py:323` (`complete_need_combination`) | **ไม่ตั้ง** |
| `plo_synthesis.py:209` (`complete_plo_synthesis`) | **ไม่ตั้ง** |

สองตัวล่างจึงใช้ default ของ provider · prompt ที่โตขึ้นพิสูจน์ว่า error **ถูกแนบเข้าไปจริง**
โมเดลอ่านแล้วตอบเหมือนเดิม

## สิ่งที่ยังไม่ได้วัด — อย่าเพิ่งสรุปแทน

1. **attempt 2/3 เคยสำเร็จบ้างไหม** ไม่รู้ · log บันทึกเฉพาะตอนล้มครบสามครั้ง
   (`Need statement rejected after 3 attempts`) ส่วนที่สำเร็จรอบสองไม่ทิ้งร่องรอยอะไรเลย
   **ตัวอย่างที่มีคือกลุ่มเดียว** จะเหมารวมว่า retry ไร้ประโยชน์ทุกกรณียังไม่ได้
2. **default temperature ของ opentyphoon เป็นเท่าไร** ไม่ได้เช็ค · ถ้าเป็น 0 อยู่แล้ว
   ผลลัพธ์ที่เหมือนกันเป๊ะก็อธิบายได้หมดและ fix ก็ชัด

## การทดลองที่ตอบได้

เรียก `complete_need_combination` บนกลุ่มที่รู้ว่าตก (`การรักษาผลประโยชน์ฯ`) n รอบ
เทียบสองเงื่อนไข — `temperature` ไม่ตั้ง vs ตั้ง > 0 เฉพาะตอน retry — แล้วนับ

- ความพยายามที่ 2 กับ 3 ให้ข้อความต่างจากที่ 1 ไหม
- มีรอบไหนผ่าน validator ไหม

ถูกและจบในไม่กี่นาที · ต้องทำก่อนแตะค่าใด ๆ

## ทางเลือกหลังวัด

| | ทำอะไร | หมายเหตุ |
|---|---|---|
| ก | ตั้ง `temperature` > 0 เฉพาะ attempt ที่ 2 ขึ้นไป | ตรงเหตุถ้าปัญหาคือ sampling · Instructor ไม่มี hook ต่อ attempt ตรง ๆ ต้องวน retry เอง |
| ข | ลด `_STATEMENT_ATTEMPTS` เหลือ 1 | ประหยัดทันทีถ้าวัดแล้ว retry ไม่เคยช่วย · เสียโอกาสในกรณีที่มันเคยช่วย |
| ค | คงไว้ | ถ้าวัดแล้ว attempt 2/3 สำเร็จบ่อยพอ |

## เก็บระหว่างทาง

`complete_need_combination` docstring ยังเขียนว่า *"Light model used for classification and
Need sentences"* — ผิดสองที่: `light` คือชื่อ slot เดิมก่อน rename และ**การ classify evidence
ไม่เรียก LLM แล้ว** (CLAUDE.md บันทึกไว้) · แก้พร้อมกันได้ตอนแตะไฟล์นี้
