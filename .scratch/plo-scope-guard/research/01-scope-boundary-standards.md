# 01 — มาตรฐานนิยาม "ขอบเขตสาขาวิชา" ของหลักสูตรไทยไว้แล้วหรือยัง

Ticket: [01-scope-boundary-standards](../issues/01-scope-boundary-standards.md)
Map: [PLO synthesis ที่ไม่หลุด scope ของหลักสูตร](../map.md)
วันที่ค้น: 2026-09-04
ประเภท: research — ไม่มีข้อเสนอ design, ไม่แตะโค้ด

**กติกาการอ้างอิง**: แหล่งปฐมภูมิเท่านั้น (UNESCO UIS, ประกาศ/กฎกระทรวง ศธ.–อว. ในราชกิจจานุเบกษา,
AUN-QA guide ฉบับจริงจากผู้จัดพิมพ์). PDF ทุกฉบับที่อ้างถูกดึงมาแปลงเป็นข้อความและอ่านจริง
ข้อความในเครื่องหมายคำพูดเป็น verbatim. ที่ใดหาแหล่งปฐมภูมิไม่ได้ เขียนไว้ตรง ๆ ว่าหาไม่ได้
และติดตรงไหน — ไม่เอาแหล่งทุติยภูมิมาถมช่อง

**คำตอบสั้น ๆ ล่วงหน้า**: มีมาตรฐานที่นิยามขอบเขตสาขาไว้จริงทั้งฝั่งสากล (ISCED-F) และฝั่งไทย
(มคอ.1) แต่**ฉบับไทยถูกยกเลิกไปทั้งชุดเมื่อ พ.ศ. 2565** และฉบับสากลให้ข้อความเฉพาะเมื่อรู้รหัส
4 หลัก ส่วน AUN-QA ไม่เคยพูดถึงเรื่องนี้เลย

---

## 1. ISCED-F 2013 (UNESCO UIS)

### แหล่ง

UNESCO Institute for Statistics, *International Standard Classification of Education —
Fields of education and training 2013 (ISCED-F 2013): Detailed field descriptions*,
Montreal, 2015. ISBN 978-92-9189-179-5, Ref UIS/2015/INS/6,
DOI 10.15220/978-92-9189-179-5-en

PDF (ดึงจาก uis.unesco.org เอง): <https://www.uis.unesco.org/sites/default/files/medias/fichiers/2025/04/international-standard-classification-of-education-fields-of-education-and-training-2013-detailed-field-descriptions-2015-en.pdf>

### สิ่งที่แหล่งนี้ให้จริง

**มีคำอธิบายขอบเขตเป็นข้อความจริง และมีทั้งฝั่ง "รวม" และฝั่ง "ไม่รวม"** — แต่**เฉพาะระดับ
detailed field (รหัส 4 หลัก)**

เอกสารประกาศเจตนาของตัวเองไว้ในบทนำ (หน้า 4) verbatim:

> "The current document describes the subject content of each of the detailed fields of the
> 2013 revision of the ISCED Fields of Education and Training classification (ISCED-F 2013).
> Where possible each description gives examples both of subjects which belong to each field
> and some boundary cases which are included in other fields. **Such exclusions help to better
> distinguish one field from another especially where the content of two fields appears to be
> similar.**"

โครงของแต่ละ entry: ประโยคนิยาม (1–4 ประโยค) → รายการ "Programmes and qualifications with
the following main content are classified here:" → บล็อก `Inclusions` (ถ้ามี) →
บล็อก `Exclusions` (ถ้ามี)

นับจากตัวไฟล์: หัวข้อ detailed field 4 หลัก **84 หัวข้อ**, บล็อก `Exclusions` **63 บล็อก**,
บล็อก `Inclusions` **28 บล็อก** — คือ detailed field ส่วนใหญ่มีถ้อยคำ "ไม่รวมถึง"
ที่ชี้ไปยังรหัสอื่นอย่างเฉพาะเจาะจง

**ข้อจำกัดเชิงโครงสร้าง**: broad field (2 หลัก) และ narrow field (3 หลัก) **ไม่มีคำอธิบาย
เป็นข้อความเลย** — ในไฟล์ บรรทัด `09 Health and Welfare` และ `091 Health` เป็นหัวข้อเปล่า ๆ
ตามด้วย `0911 Dental studies` ทันที ข้อยกเว้นเดียวคือ broad field `00 Generic programmes
and qualifications` ที่มีย่อหน้าอธิบาย (เพราะต้องกันคนใช้เป็นถังขยะ)

### ตัวอย่างถ้อยคำจริง

**(ก) 0913 Nursing and midwifery** — entry ที่สมบูรณ์ที่สุด: นิยาม + inclusion + exclusion 4 ข้อ

> Nursing is the study of providing health care for the sick, disabled or infirm and assisting
> physicians and other medical and health professionals diagnose and treat patients. The focus
> of qualifications in nursing is maintaining and caring for the health of patients during illness
> and rehabilitation. It includes health care of old people and health care of the disabled.
> Midwifery is the study of providing care to childbearing women during pregnancy, labour and
> birth and during the postpartum period. It also includes caring for the new born and assisting
> the mother with breast feeding.
>
> Programmes and qualifications with the following main content are classified here:
> Assistant nursing / Basic nursing / General nursing / Health care of old people /
> Heath care of the disabled / Health care programmes / Infant hygiene (nursing) / Midwifery /
> Nursing aide/Orderly / Psychiatric nursing / Specialised nursing
>
> **Inclusions**
> Care programmes comprising both health care and social care e.g. for old people, are included here.
>
> **Exclusions**
> Veterinary nursing is excluded from this detailed field and is included in detailed field 0841 `Veterinary'.
> Dental nursing is excluded from this detailed field and is included in detailed field 0911 `Dental studies'.
> Non-medical care of children (not health care) is excluded from this detailed field and included
> in detailed field 0922 `Child care and youth services'.
> Non-medical care of the elderly (not health care) is excluded from this detailed field and included
> in detailed field 0921 `Care of the elderly and disabled adults'.

**(ข) 0613 Software and applications development and analysis** — นิยามสั้น แต่ exclusion
ตรงกับเคสที่ map นี้กลัวพอดี (skill ฮาร์ดแวร์ / เน็ตเวิร์ก / การใช้โปรแกรม โผล่มาในหลักสูตรซอฟต์แวร์)

> Software and applications development and analysis is the study of the design and development
> of computer systems and computing environments.
>
> **Exclusions**
> Computer engineering (hardware) is excluded from this detailed field and included in detailed
> field 0714 `Electronics and automation'.
> Programmes and qualifications in using computer applications are excluded from this detailed
> field and included in detailed field 0611 `Computer use'. Database and network design and
> administration is excluded from this detailed field and included in detailed field 0612
> `Database and network design and administration'.

**(ค) 0917 Traditional and complementary medicine and therapy** — entry ที่**บางที่สุด** และเป็น
field ที่ตรงกับหลักสูตรไทย (แพทย์แผนไทย / แพทย์ทางเลือก) ทั้ง entry คือประโยคเดียว:

> Traditional and complementary medicine is the study of alternative medicine.

ตามด้วยรายการหัวข้อ (Acupuncture and oriental medicine, Aromatherapy, Ayurvedic medicine,
Herbalism, Herbology, Holistic medicine, Homeopathic medicine, Traditional medicine, for example
Chinese) — **ไม่มี Inclusions ไม่มี Exclusions** และไม่เอ่ยถึงแพทย์แผนไทยเลย

*(ตัวอย่างเสริม 0411 Accounting and taxation ทั้ง entry คือ "Accounting and taxation is the
study of maintaining, auditing and recording financial transactions." + exclusion บรรทัดเดียว
"Study of tax laws is excluded from this detailed field and included in detailed field 0421 `Law'.")*

### ข้อสังเกตที่กระทบ ticket 02

- **หลักสูตรสหวิทยาการ**: ISCED-F แก้ด้วยรหัส `0x88` และกฎ "เวลาเรียนส่วนใหญ่ตกอยู่ที่ไหน" เช่น 0788:
  > "Inter-disciplinary or broad programmes and qualifications to which the greatest intended
  > learning time is devoted to engineering, manufacturing and construction are classified here."

  คือ ISCED-F **ยุบ**ความเป็นสองขาลงเหลือรหัสเดียว ไม่ได้บรรยายขอบเขตของหลักสูตรสองขา —
  เป็นกฎสำหรับนักสถิติ ไม่ใช่คำอธิบายสำหรับ designer ช่องว่างที่ map เขียนไว้ใน
  "Not yet specified — หลักสูตรสหวิทยาการ" **ยังเปิดอยู่หลังงานวิจัยชิ้นนี้**
- **ภาษา**: ฉบับ Detailed field descriptions ที่เข้าถึงได้เป็น**ภาษาอังกฤษ** UIS มีคำแปล
  ISCED-F manual เป็น ES/RU/AR — **หาฉบับภาษาไทยไม่เจอ** (ค้น uis.unesco.org,
  unesdoc.unesco.org, isced.uis.unesco.org) **ไม่มีแหล่งปฐมภูมิยืนยันว่ามีฉบับไทย**
  ถ้าจะเอาข้อความนี้ไปให้ designer อ่าน ต้องแปลเอง
- **สภาพใน repo ตอนนี้**: `src/curriculum_agent/data/isced.py` เก็บ `BROAD_FIELDS`,
  `NARROW_FIELDS`, `DETAILED_FIELDS` เป็น `IscedField(code, name_en, name_th)` —
  **มีแต่รหัสกับชื่อ ไม่มี description แม้แต่ field เดียว** และ
  `ProgramCreateRequest._validate_isced_code` (`models.py:162-166`) แค่ตรวจว่ารหัสอยู่ใน
  taxonomy ข้อความขอบเขตทั้งหมดข้างบน**ยังไม่มีอยู่ใน repo** ต้องนำเข้าใหม่ถ้าจะใช้
- **ข้อมูลอาจว่าง**: `isced_code: str | None = None` และตาม CLAUDE.md ฟอร์ม intake เก็บแค่
  university / faculty / field / degree_level / duration — **ไม่ได้ถาม ISCED code**
  โปรแกรมจริงส่วนใหญ่จึงน่าจะไม่มีรหัสนี้ติดมา

### Verdict

**เพาะ scope statement ได้จริง แต่มีเงื่อนไขสองชั้น** — ต้องรู้รหัส **4 หลัก** (รหัส 2–3 หลัก
ไม่ให้ข้อความอะไรเลย) และคุณภาพไม่สม่ำเสมอ: 0913 / 0613 ให้ทั้ง "ครอบคลุมอะไร" และ "ไม่รวมอะไร"
ในระดับที่ designer แก้ต่อได้ทันที ส่วน 0917 ให้ประโยคเดียวที่แทบไม่ต่างจากกระดาษเปล่า

---

## 2. มคอ.1 (มาตรฐานคุณวุฒิระดับอุดมศึกษาแห่งชาติ สาขา/สาขาวิชา)

### 2.1 สถานะทางกฎหมาย — สำคัญที่สุดในหัวข้อนี้: **มคอ.1 ถูกยกเลิกทั้งชุดแล้ว**

**กฎกระทรวง มาตรฐานคุณวุฒิระดับอุดมศึกษา พ.ศ. ๒๕๖๕** — ราชกิจจานุเบกษา เล่ม ๑๓๙ ตอนที่ ๒๐ ก
หน้า ๒๘–๓๑ ลงวันที่ ๓๑ มีนาคม ๒๕๖๕ (ให้ไว้ ณ วันที่ 10 มีนาคม ๒๕๖๕, เอนก เหล่าธรรมทัศน์)
PDF: <https://ratchakitcha.soc.go.th/documents/17202623.pdf>

**ข้อ ๒ verbatim:**

> ข้อ ๒ ให้ยกเลิกประกาศกระทรวงศึกษาธิการและประกาศคณะกรรมการการอุดมศึกษาทุกฉบับที่เกี่ยวกับ
> กรอบมาตรฐานคุณวุฒิระดับอุดมศึกษาแห่งชาติ แนวทางการปฏิบัติตามกรอบมาตรฐานคุณวุฒิระดับอุดมศึกษา
> แห่งชาติ **และมาตรฐานคุณวุฒิในสาขาหรือสาขาวิชา ทั้งนี้ ไม่ว่าในระดับใด สาขาใด หรือสาขาวิชาใด**

"มาตรฐานคุณวุฒิในสาขาหรือสาขาวิชา" คือชื่อทางกฎหมายของ มคอ.1 → **มคอ.1 ทุกฉบับ ทุกสาขา
ถูกยกเลิก** มีผลเมื่อพ้น 180 วันนับแต่ ๓๑ มี.ค. ๒๕๖๕ (ข้อ ๑) คือประมาณ ๒๗ ก.ย. ๒๕๖๕

สิ่งที่มาแทนคือ **ผลลัพธ์การเรียนรู้สี่ด้านแบบ generic ล้วน** — ไม่มีเนื้อหาสาขาเลย (ข้อ ๗ verbatim):

> ข้อ ๗ ผลลัพธ์การเรียนรู้ของผู้สำเร็จการศึกษาทุกระดับมาตรฐานคุณวุฒิระดับอุดมศึกษา
> ต้องมีอย่างน้อยสี่ด้าน ดังต่อไปนี้
> (๑) ด้านความรู้ (๒) ด้านทักษะ (๓) ด้านจริยธรรม (๔) ด้านลักษณะบุคคล

ประตูสำหรับมาตรฐานรายสาขายังเปิดอยู่ แต่ต้องออกใหม่โดย กมอ. (ข้อ ๘ verbatim):

> ข้อ ๘ นอกจากผลลัพธ์การเรียนรู้ตามข้อ ๗ คณะกรรมการอาจประกาศกำหนดผลลัพธ์การเรียนรู้ด้านอื่น
> เพิ่มเติมหรือกำหนดรายละเอียดผลลัพธ์การเรียนรู้เพิ่มขึ้นตามความจำเป็นทางวิชาการหรือวิชาชีพ
> ของแต่ละสาขาหรือสาขาวิชา โดยประกาศเป็นมาตรฐานคุณวุฒิในสาขาหรือสาขาวิชาก็ได้

และหลักฐานฝั่งลบอีกชิ้น — **กฎกระทรวง มาตรฐานหลักสูตรการศึกษาระดับอุดมศึกษา พ.ศ. ๒๕๖๕**
(ราชกิจจานุเบกษา เล่ม ๑๓๙ ตอนที่ ๒๐ ก หน้า ๑๕–๑๖ ลงวันที่ ๓๑ มีนาคม ๒๕๖๕,
<https://ratchakitcha.soc.go.th/documents/17202620.pdf>) **ข้อ ๑๒** ระบุรายการที่หลักสูตร
"ต้องประกอบด้วย" ครบทั้งสิบข้อ verbatim:

> (๑) ชื่อปริญญา ประกาศนียบัตรบัณฑิต ประกาศนียบัตรบัณฑิตชั้นสูง และสาขาวิชา
> (๒) ปรัชญา วัตถุประสงค์ และผลลัพธ์การเรียนรู้
> (๓) โครงสร้างหลักสูตร รายวิชาและหน่วยกิต
> (๔) การจัดกระบวนการเรียนรู้
> (๕) ความพร้อมและศักยภาพในการบริหารจัดการหลักสูตร ซึ่งรวมถึงคณาจารย์และที่ปรึกษาวิทยานิพนธ์
> (๖) คุณสมบัติของผู้เข้าศึกษา
> (๗) การประเมินผลการเรียนและเกณฑ์การสำเร็จการศึกษา
> (๘) การประกันคุณภาพหลักสูตร
> (๙) ระบบและกลไกในการพัฒนาหลักสูตร
> (๑๐) รายการอื่นตามที่คณะกรรมการประกาศกำหนด

**ไม่มีรายการใดเป็น "ขอบเขตของสาขาวิชา"** — กฎหมายปัจจุบันขอชื่อ สาขาวิชา ปรัชญา วัตถุประสงค์
และผลลัพธ์การเรียนรู้ แต่ไม่เคยขอข้อความว่าสาขานี้ครอบคลุมหรือไม่ครอบคลุมอะไร

**ช่องที่หาไม่เจอ (บันทึกไว้ตรง ๆ)**: มีหลักฐานว่า กมอ. ออก "มาตรฐานคุณวุฒิในสาขาวิชา..." ชุดใหม่
ตามข้อ ๘ แล้ว (แพทยศาสตร์ พ.ศ. 2566 ปรากฏบนดัชนี ops.go.th; กายภาพบำบัด / เทคนิคการแพทย์ /
เภสัชศาสตร์ พ.ศ. 2567 ปรากฏในผลค้น) — แต่ **ดึงตัวบทฉบับเต็มมาอ่านไม่สำเร็จ**:
ratchakitcha.soc.go.th ตอบ Cloudflare challenge / 403 กับทั้ง curl และ WebFetch เมื่อค้นหา,
และ ops.go.th timeout จึง **ยังตอบไม่ได้ว่ามาตรฐานรายสาขาชุดใหม่ยังมีหัวข้อ "ลักษณะของสาขา"
อยู่หรือไม่** ถ้า ticket 02 จะพึ่งของชุดใหม่ ต้องไปเปิดตัวบทก่อน

### 2.2 มคอ.1 ฉบับเดิมเขียนขอบเขตไว้ตรงไหน

แม้ถูกยกเลิกแล้ว เอกสารยังหมุนเวียนใช้เป็น reference อยู่ จึงบันทึกโครงไว้:
เปิด มคอ.1 จริงได้ **9 ฉบับ** (พยาบาลศาสตร์ 2560, แพทยศาสตร์ 2561, การบัญชี 2562,
นิติศาสตร์ 2561, กายภาพบำบัด 2556, วิศวกรรมศาสตร์ 2553, ครุศาสตร์/ศึกษาศาสตร์ 4 ปี 2562,
เทคโนโลยี 2560, ภาษาอังกฤษ 2560) ทุกฉบับใช้โครงเดียวกัน:

```
๑. ชื่อสาขา/สาขาวิชา              ← บางฉบับแจกแจงสาขาย่อยไว้ตรงนี้
๒. ชื่อปริญญา
๓. ลักษณะของสาขา/สาขาวิชา          ← ★ ขอบเขตอยู่ที่นี่ (ร้อยแก้ว)
๔. คุณลักษณะของบัณฑิตที่พึงประสงค์
๕. มาตรฐานผลการเรียนรู้
๖. องค์กรวิชาชีพที่เกี่ยวข้อง
๗. โครงสร้างหลักสูตร
๘. เนื้อหาสาระสำคัญของสาขา/สาขาวิชา ← ★ ขอบเขตเชิงองค์ความรู้ (รายการ)
๙.–๑๖. กลยุทธ์การสอน / ทวนสอบ / คณาจารย์ / ประกันคุณภาพ ...
```

**หัวข้อที่ ticket เดาไว้ แต่ตรวจแล้วไม่มีจริง**: ไม่มีฉบับใดใน 9 ฉบับที่มีหัวข้อชื่อ
"ขอบเขตของสาขาวิชา" หรือ "ขอบข่ายของสาขาวิชา" — คำว่า "ขอบเขต" โผล่เป็นข้อความในเนื้อเท่านั้น
ส่วน "ปรัชญาและวัตถุประสงค์ของหลักสูตร" ไม่ใช่หัวข้อของ มคอ.1 แต่เป็นของ **มคอ.2**
ที่มหาวิทยาลัยเขียนเอง

**ลักษณะถ้อยคำ**: ข้อ ๓ เป็นร้อยแก้ว 1–3 ย่อหน้า สูตร "สาขา X เป็น{วิชาชีพ/ศาสตร์}ที่…"
แล้วต่อด้วย "ครอบคลุม…" / "เกี่ยวข้องกับ…" — **ไม่ใช่รายการอาชีพ** (เส้นทางอาชีพไม่ปรากฏ
ใน มคอ.1 เลย) ข้อ ๘ เป็นบัญชีองค์ความรู้

**ถ้อยคำกันออก (exclusion): ศูนย์** — grep `ไม่รวมถึง`, `มิได้ครอบคลุม`, `ไม่ครอบคลุม`,
`ไม่รวม`, `มิใช่` ในข้อความที่แกะได้ทั้ง 9 ฉบับ **ไม่พบเลยแม้แต่ครั้งเดียว** มคอ.1 นิยามสาขา
แบบ "รวมอะไรบ้าง" อย่างเดียว และข้อ ๘ ยังประกาศตัวว่าเป็น**พื้นขั้นต่ำ ไม่ใช่เพดาน**
(พยาบาลศาสตร์ 2560: "แต่หลักสูตรต้องมีเนื้อหาสาระครอบคลุมตามที่กำหนดเป็นอย่างน้อย")

### ตัวอย่างถ้อยคำจริง

**(ก) มคอ.1 สาขาพยาบาลศาสตร์ พ.ศ. ๒๕๖๐** — ประกาศกระทรวงศึกษาธิการ, ราชกิจจานุเบกษา
เล่ม ๑๓๕ ตอนพิเศษ ๑ ง หน้า ๗, ๓ มกราคม ๒๕๖๑
ไฟล์: <https://www.tnmc.or.th/images/userfiles/files/Edit(1).PDF> — ไฟล์ประกาศฯ ฉบับ
ราชกิจจานุเบกษา (มีหัวกระดาษราชกิจจาฯ ครบ) โฮสต์โดย **สภาการพยาบาล** ไม่ใช่ ratchakitcha เอง

> **๓. ลักษณะของสาขา**
> สาขาพยาบาลศาสตร์เป็นวิชาชีพที่ต้องปฏิบัติโดยตรงต่อชีวิต สุขภาพและอนามัยของประชาชน
> ด้วยความเอาใจใส่อย่างเอื้ออาทร จำเป็นต้องใช้ศาสตร์และศิลป์ทางการพยาบาล การผดุงครรภ์
> ศาสตร์ที่เกี่ยวข้องและหลักฐานเชิงประจักษ์ เพื่อให้การพยาบาลองค์รวมแก่ผู้รับบริการที่เป็นบุคคล
> ครอบครัว และชุมชน ในทุกมิติ ทุกภาวะสุขภาพ และทุกช่วงชีวิต โดยคำนึงถึงความแตกต่างทางวัฒนธรรม
> ของผู้รับบริการ การเปลี่ยนแปลงของสังคม ความก้าวหน้าของศาสตร์ทางการพยาบาล ศาสตร์ที่เกี่ยวข้อง
> และเทคโนโลยีทางการแพทย์ รวมถึงเทคโนโลยีสารสนเทศ ที่สนองตอบความต้องการของประชาชนและ
> ผู้รับบริการสุขภาพ …

**(ข) มคอ.1 สาขาวิชาแพทยศาสตร์ พ.ศ. ๒๕๖๑** — ตัวอย่างที่กระชับที่สุด ประโยคเดียวจบ
ใช้ "ครอบคลุม" กำหนดขอบเขตตรง ๆ และผูกปลายทางไว้กับแพทยสภา
ไฟล์ประกาศฯ (มีหัวราชกิจจาฯ) โฮสต์โดย ม.อุบลราชธานี:
<https://www.ubu.ac.th/web/files_up/46f2019021511525621.pdf>

> **๓. ลักษณะของสาขาวิชา**
> สาขาวิชาแพทยศาสตร์เป็นสาขาของวิทยาศาสตร์สุขภาพที่เกี่ยวกับการนำความรู้ทางวิทยาศาสตร์
> และศิลปศาสตร์มาใช้ในการบริบาลเวชกรรม ซึ่งครอบคลุมการดูแลรักษาสุขภาพของมนุษย์เพื่อการสร้างเสริม
> สุขภาพ การป้องกันโรค การตรวจวินิจฉัย การบำบัดโรคและความเจ็บป่วย และการฟื้นฟูสมรรถภาพ
> ตามเกณฑ์มาตรฐานผู้ประกอบวิชาชีพเวชกรรมของแพทยสภา

และข้อ ๘ ของฉบับเดียวกัน แสดงรูปแบบ "รายการองค์ความรู้":

> **๘. เนื้อหาสาระสำคัญของสาขาวิชา**
> เนื้อหาสาระสำคัญของสาขาวิชาแพทยศาสตร์ ประกอบด้วย
> (๑) โครงสร้าง หน้าที่ และกลไกการทำงานของร่างกายและจิตใจของมนุษย์ในภาวะปกติ
> (๒) สาเหตุ พยาธิกำเนิด พยาธิสภาพ พยาธิสรีรวิทยาของโรค อาการ และอาการแสดงที่พบในภาวะผิดปกติ
> ของร่างกายและจิตใจของมนุษย์ …
> ทั้งนี้ เนื้อหาต้องสอดคล้องกับเกณฑ์ความรู้ความสามารถในการประเมินเพื่อรับใบอนุญาต
> เป็นผู้ประกอบวิชาชีพเวชกรรมของแพทยสภา

**(ค) มคอ.1 สาขาวิชากายภาพบำบัด พ.ศ. ๒๕๕๖** — boundary ชัดที่สุด เพราะระบุทั้งประชากรเป้าหมาย
และวิธีการที่นับเป็นของสาขา (เอกสารแนบท้ายประกาศ ศธ., ไม่มีหน้าราชกิจจาฯ ติดมา):
<https://www.ubu.ac.th/web/files_up/46f2014123010552627.pdf>

> **๓ ลักษณะของสาขาวิชา**
> สาขาวิชากายภาพบำบัดเป็นวิชาชีพที่ต้องปฏิบัติโดยตรงต่อมนุษย์ทุกวัย ทั้งในคนที่มีปัญหาสุขภาพ
> จากภาวะโรค การบาดเจ็บ ภาวะเสื่อม และคนปกติ โดยอ้างอิงเหตุผลและหลักฐานทางวิทยาศาสตร์
> ในการตรวจประเมิน การวินิจฉัย การบำบัดรักษา และการฟื้นฟูสภาพร่างกาย รวมทั้งการป้องกัน
> การส่งเสริมสุขภาพของร่างกายและจิตใจด้วยวิธีการทางกายภาพบำบัด โดยจัดการเรียนการสอน
> ตามองค์ความรู้ทั้งในทางทฤษฎี และทักษะปฏิบัติทางวิชาชีพกายภาพบำบัด เช่น การรักษาด้วยการออกกำลังกาย
> การรักษาด้วยไฟฟ้า การรักษาด้วยมือ และการรักษาด้วยน้ำ เป็นต้น …

*(เสริม: มคอ.1 การบัญชี พ.ศ. ๒๕๖๒ — ราชกิจจานุเบกษา เล่ม ๑๓๖ ตอนพิเศษ ๗๘ ง หน้า ๑๓,
๒๘ มีนาคม ๒๕๖๒, <https://www.ubu.ac.th/web/files_up/00046f2019072315352573.pdf> — "๓. ลักษณะของ
สาขาวิชาการบัญชี / สาขาวิชาการบัญชี มีลักษณะความเป็นศาสตร์และศิลป์อยู่ด้วยกัน เกี่ยวข้องกับ
เศรษฐกิจ สังคม และเทคโนโลยีสารสนเทศ …")*

### ข้อจำกัดของการค้นครั้งนี้ (บันทึกไว้ตรง ๆ)

1. **ratchakitcha.soc.go.th บล็อกการค้นหา** — หน้า search และ API คืน Cloudflare challenge / 403
   ทั้ง curl และ WebFetch. เข้าถึงได้เฉพาะ path `/documents/{id}.pdf` แบบเดารหัส ซึ่งใช้ได้กับ
   กฎกระทรวง 2565 (หาเจอ) แต่ใช้หา มคอ.1 รายฉบับไม่ได้
2. **www.mua.go.th (สกอ. legacy) ตายแล้ว** (`ENOTFOUND`) และ ops.go.th timeout — จึงต้องใช้ไฟล์
   ประกาศฯ ที่โฮสต์โดยสภาวิชาชีพ / มหาวิทยาลัย โดยตรวจว่ามีหัวกระดาษราชกิจจานุเบกษาในตัวไฟล์
   เป็นเกณฑ์ยืนยัน (ทำได้กับ พยาบาลศาสตร์ 2560, แพทยศาสตร์ 2561, การบัญชี 2562, นิติศาสตร์ 2561,
   ครุศาสตร์ 2562, เทคโนโลยี 2560; ส่วนกายภาพบำบัด 2556, วิศวกรรมศาสตร์ 2553, ภาษาอังกฤษ 2560
   เป็นไฟล์ "เอกสารแนบท้ายประกาศ ศธ." ที่ไม่มีหน้าราชกิจจาฯ)
3. **4 ฉบับแกะข้อความไม่ได้** (คอมพิวเตอร์ 2552, โลจิสติกส์ 2552, การท่องเที่ยวและการโรงแรม 2553
   และไฟล์พยาบาลศาสตร์ฉบับ ubu) — ฝัง font TIS-620 ไม่มี ToUnicode ต้อง OCR **จึงไม่มีการยกข้อความ
   จากสี่ฉบับนี้**
4. **มาตรฐานคุณวุฒิรายสาขาชุดใหม่หลัง 2565 — ยังไม่ได้อ่านตัวบท** (ดู §2.1)

### Verdict

**เพาะได้ดีที่สุดในสามแหล่ง แต่ของถูกยกเลิกไปแล้ว** — "๓. ลักษณะของสาขา" คือ scope statement
ภาษาไทยที่เขียนไว้แล้วจริง ๆ โดยกระทรวง ยาวกำลังดี และเป็นแบบที่ designer ไทยคุ้นตา
แต่ (ก) เป็นด้านบวกล้วน ไม่มี exclusion เลยสักคำ (ข) กฎกระทรวง 2565 ข้อ ๒ ยกเลิกไปหมดแล้ว
ทุกสาขาทุกระดับ (ค) `parsers/mko1_parser.py` ยังเป็น `NotImplementedError` stub

---

## 3. AUN-QA (ASEAN University Network Quality Assurance)

### แหล่ง

- **v4.0** — *Guide to AUN-QA Assessment at Programme Level, Version 4.0*, ASEAN University
  Network, ตุลาคม 2020, 111 หน้า. **ดึงจาก aunsec.org เอง (ผู้จัดพิมพ์)** — ยืนยัน HTTP 200,
  `application/pdf`:
  <https://www.aunsec.org/application/files/2816/7290/3752/Guide_to_AUN-QA_Assessment_at_Programme_Level_Version_4.0_4.pdf>
- **v3.0** — *…Version 3.0*, ตุลาคม 2015 ยืนยันความเป็นฉบับทางการจาก imprint ในตัวไฟล์
  แต่ **host ไม่ใช่ aunsec.org** — เป็น CETQA, Vietnam National University HCMC.
  **หา v3.0 บนเว็บผู้จัดพิมพ์เองไม่เจอ**

### สิ่งที่แหล่งนี้ให้จริง

Criterion ที่ว่าด้วย ELO คือ **Criterion 1 – Expected Learning Outcomes** ทั้งสองเวอร์ชัน
(v4.0 หัวข้อ "2.1 AUN-QA Criterion 1 – Expected Learning Outcomes" จาก 8 criteria;
v3.0 หัวข้อ "2.1 Expected Learning Outcomes" จาก 11 criteria)

**v4.0 Requirements (หน้า 16) verbatim:**

> **1.1.** The programme to show that the expected learning outcomes are appropriately formulated
> in accordance with an established learning taxonomy, are aligned to the vision and mission of
> the university, and are known to all stakeholders.
>
> **1.3.** The programme to show that the expected learning outcomes consist of both generic
> outcomes (related to written and oral communication, problem-solving, information technology,
> teambuilding skills, etc) and **subject specific outcomes (related to knowledge and skills of
> the study discipline)**.
>
> **1.4.** The programme to show that the requirements of the stakeholders, especially the
> external stakeholders, are gathered, and that these are reflected in the expected learning outcomes.

**v3.0 checklist (หน้า 16) verbatim:**

> **1.1** The expected learning outcomes have been clearly formulated and aligned with the vision
> and mission of the university [1,2]
> **1.2** The expected learning outcomes cover both subject specific and generic (i.e.
> transferable) learning outcomes [3]
> **1.3** The expected learning outcomes clearly reflect the requirements of the stakeholders [4]

**Diagnostic questions ของ Criterion 1 (v4.0 หน้า 17)** — ข้อที่ใกล้ "สาขานี้ครอบคลุมอะไร"
ที่สุดคือข้อแรก และมันถามถึง *purpose* ไม่ใช่ขอบเขต:

> - What is the purpose of the study programme?
> - Do the expected learning outcomes reflect the vision and mission of the university, the
>   faculty, and the department?
> - Does the labour market set specific requirements for the graduates to meet?
> - To what extent is the content of the programme tuned to the needs of the labour market?
> - Are there well-defined job profiles?

### หลักฐานฝั่งลบ (full-text keyword sweep ทั้งสองเล่ม)

- `distinctive` — **0 ครั้ง** ทั้ง v4.0 และ v3.0
- `unique` / `uniqueness` — **0 ครั้ง** ทั้งสองเล่ม
- `boundary` — **0 ครั้ง** ทั้งสองเล่ม
- `identity` — **0 ครั้ง** ทั้งสองเล่ม
- `scope` — v4.0 มี 5 ครั้ง **ทั้งหมดหมายถึงขอบเขตของการประเมิน** ไม่ใช่ขอบเขตของสาขา
- `discipline` — v4.0 โผล่ใน requirement 1.3, ในคุณสมบัติผู้ประเมิน ("Two experts on the subject
  area or discipline being assessed"), และใน appendix — **ไม่เคยเป็นสิ่งที่หลักสูตรต้องขีดเส้น**
- `qualifications framework` — **ไม่มีเลยใน v3.0**; ใน v4.0 มีเฉพาะใน addendum ของหลักสูตร
  บัณฑิตศึกษาแบบวิจัย และเป็นเชิงพรรณนา ไม่ใช่ข้อกำหนดของ Criterion 1

สิ่งที่ใกล้เคียงที่สุดในทั้งเล่มอยู่ใน **Criterion 2 ไม่ใช่ Criterion 1** — programme
specification content list (v4.0 หน้า 19–20) ขอ "Programme title", "Name of the final award",
"A summary of the programme aims and intended learning outcomes", "Relevant benchmark reports,
external and internal reference points…" — คือชื่อ ปริญญา จุดมุ่งหมาย และ benchmark
**ไม่มีข้อความว่าสาขาครอบคลุมหรือไม่ครอบคลุมอะไร**

### Verdict

**เพาะไม่ได้ และอ้างเป็นเหตุผลก็ไม่ได้** — AUN-QA ไม่เคยเรียกร้องหรือให้แม่แบบของ field boundary
คันโยกที่มีจริงมีสองอัน: (ก) vision/mission alignment ใน 1.1 และ (ข) การแยก subject-specific
ใน 1.3 — อันหลังเป็น *การจำแนกประเภทของ outcome* ไม่ใช่ *การขีดเส้นขอบสาขา*
scope statement จะเป็นของที่เพิ่มขึ้นมาเกิน AUN-QA — มีเหตุผลของตัวเองได้ แต่**อย่าอ้าง
AUN-QA เป็นที่มา**

---

## What this means for ticket 02

**ตอบตรง ๆ: ควรเป็น "แบบฟอร์มที่มีของตั้งต้นและแก้ได้" ไม่ใช่กระดาษเปล่า — แต่ตัวเพาะที่พึ่งได้
มีอันเดียว คือ ISCED-F detailed field ไม่ใช่ มคอ.1**

เหตุผลเรียงตามน้ำหนัก:

1. **มีของเขียนไว้แล้วจริง เลยไม่มีเหตุผลจะให้กระดาษเปล่า** — ทั้ง ISCED-F 0913/0613 และ
   มคอ.1 "ข้อ ๓ ลักษณะของสาขา" พิสูจน์ว่าถ้อยคำระดับที่ต้องการเขียนได้และเคยเขียนมาแล้ว
   ตัวอย่างเหล่านี้ใช้เป็น few-shot / เป็น placeholder ให้ designer แก้ได้ทันที
2. **แต่ มคอ.1 พึ่งเป็นแหล่งอัตโนมัติไม่ได้** — ถูกยกเลิกทั้งชุดโดยกฎกระทรวง 2565 ข้อ ๒,
   ไม่มี API/ดัชนีทางการที่เข้าถึงได้ (ratchakitcha บล็อก, mua.go.th ตายแล้ว), หลายฉบับแกะ
   ข้อความไม่ได้ต้อง OCR, และ `parsers/mko1_parser.py` ยังเป็น stub ใช้ได้อย่างมากก็เป็น
   **สิ่งที่ designer แนบเองเป็น evidence** (`stakeholder_type` ฝั่ง requirement) ไม่ใช่
   seed อัตโนมัติของฟอร์ม
3. **ISCED-F เพาะได้ แต่ต้องรับสามเงื่อนไข**: (ก) ต้องมีรหัส 4 หลัก ซึ่ง intake ตอนนี้
   **ไม่ได้ถาม** และ `isced_code` เป็น optional (ข) `data/isced.py` มีแต่ code/name
   **ต้องนำเข้าตัว description เพิ่ม** (ค) เป็นภาษาอังกฤษ ไม่มีฉบับไทย ต้องแปล
   → ถ้าเลือกทางนี้ ticket 02 กำลังตัดสินใจสามอย่างพร้อมกัน ไม่ใช่หนึ่ง
4. **ไม่มีแหล่งไหนให้ฝั่ง "ไม่รวมอะไร" เป็นภาษาไทย** — ISCED-F มี exclusion แต่เป็นอังกฤษ
   และเป็นการชี้ไปยังรหัส ISCED อื่น (ซึ่ง designer ไทยไม่ได้คิดเป็นรหัส); มคอ.1 มี
   **ศูนย์ exclusion**; AUN-QA ไม่มีอะไรเลย → ถ้า scope statement ของเราต้องการฝั่งลบ
   (ซึ่ง map บอกว่านั่นคือหัวใจ — กัน Need "นอกสาขาเลย") **ต้องให้ designer เขียนเอง
   ไม่มีมาตรฐานไหนเพาะให้ได้**
5. **หลักสูตรสหวิทยาการยังตอบไม่ได้เหมือนเดิม** — ISCED-F ยุบเหลือรหัส `0x88` ตามเวลาเรียน
   ส่วนใหญ่ ไม่ได้บรรยายขอบเขตสองขา; มคอ.1 ก็นิยามทีละสาขา ช่องว่างใน map ข้อนี้
   **ไม่ปิดด้วยงานวิจัยชิ้นนี้**
6. **AUN-QA เป็นทางตัน** — อย่าเขียนใน spec ว่า scope statement "รองรับ AUN-QA Criterion 1"
   เพราะ keyword sweep ยืนยันว่าไม่มีข้อความรองรับ ถ้าจะอ้างเหตุผลด้านมาตรฐาน
   อ้าง traceability ของ rule 2 และ ISCED-F ได้ แต่ AUN-QA ไม่ได้

**รูปที่หลักฐานชี้ไป**: ช่องกรอก 2 ช่อง — "ครอบคลุม" (เพาะจาก ISCED-F description ถ้ามีรหัส
4 หลัก, ว่างถ้าไม่มี) และ "ไม่รวมถึง" (ว่างเสมอ ไม่มีมาตรฐานไหนเพาะให้ได้) — แต่นั่นเป็น
เรื่องของ ticket 02 ตัดสิน ไม่ใช่ข้อเสนอของเอกสารนี้
