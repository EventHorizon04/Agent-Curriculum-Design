from __future__ import annotations

from typing import NamedTuple


class IscedField(NamedTuple):
    code: str
    name_en: str
    name_th: str


BROAD_FIELDS: list[IscedField] = [
    IscedField("00", "Generic programmes and qualifications", "หลักสูตรและคุณวุฒิทั่วไป"),
    IscedField("01", "Education", "ศึกษาศาสตร์"),
    IscedField("02", "Arts and humanities", "ศิลปกรรมศาสตร์และมนุษยศาสตร์"),
    IscedField(
        "03", "Social sciences, journalism and information", "สังคมศาสตร์ วารสารศาสตร์ และสารสนเทศ"
    ),
    IscedField("04", "Business, administration and law", "บริหารธุรกิจ การจัดการ และกฎหมาย"),
    IscedField(
        "05",
        "Natural sciences, mathematics and statistics",
        "วิทยาศาสตร์ธรรมชาติ คณิตศาสตร์ และสถิติ",
    ),
    IscedField(
        "06", "Information and Communication Technologies (ICTs)", "เทคโนโลยีสารสนเทศและการสื่อสาร"
    ),
    IscedField(
        "07", "Engineering, manufacturing and construction", "วิศวกรรมศาสตร์ การผลิต และการก่อสร้าง"
    ),
    IscedField(
        "08",
        "Agriculture, forestry, fisheries and veterinary",
        "เกษตรศาสตร์ ป่าไม้ ประมง และสัตวแพทยศาสตร์",
    ),
    IscedField("09", "Health and welfare", "สาธารณสุขและสวัสดิการสังคม"),
    IscedField("10", "Services", "การบริการ"),
]

NARROW_FIELDS: list[IscedField] = [
    IscedField("001", "Basic programmes and qualifications", "หลักสูตรพื้นฐานทั่วไป"),
    IscedField("002", "Literacy and numeracy", "การรู้หนังสือและการคำนวณ"),
    IscedField("003", "Personal skills and development", "ทักษะและการพัฒนาส่วนบุคคล"),
    IscedField("011", "Education", "ศึกษาศาสตร์"),
    IscedField("021", "Arts", "ศิลปกรรมศาสตร์"),
    IscedField("022", "Humanities (except languages)", "มนุษยศาสตร์ (ไม่รวมภาษา)"),
    IscedField("023", "Languages", "ภาษา"),
    IscedField("031", "Social and behavioural sciences", "สังคมศาสตร์และพฤติกรรมศาสตร์"),
    IscedField("032", "Journalism and information", "วารสารศาสตร์และสารสนเทศ"),
    IscedField("041", "Business and administration", "บริหารธุรกิจและการจัดการ"),
    IscedField("042", "Law", "นิติศาสตร์"),
    IscedField("051", "Biological and related sciences", "ชีววิทยาและสาขาที่เกี่ยวข้อง"),
    IscedField("052", "Environment", "สิ่งแวดล้อม"),
    IscedField("053", "Physical sciences", "วิทยาศาสตร์กายภาพ"),
    IscedField("054", "Mathematics and statistics", "คณิตศาสตร์และสถิติ"),
    IscedField(
        "061", "Information and Communication Technologies (ICTs)", "เทคโนโลยีสารสนเทศและการสื่อสาร"
    ),
    IscedField("071", "Engineering and engineering trades", "วิศวกรรมศาสตร์และช่างเทคนิควิศวกรรม"),
    IscedField("072", "Manufacturing and processing", "การผลิตและการแปรรูป"),
    IscedField("073", "Architecture and construction", "สถาปัตยกรรมศาสตร์และการก่อสร้าง"),
    IscedField("081", "Agriculture", "เกษตรศาสตร์"),
    IscedField("082", "Forestry", "วนศาสตร์"),
    IscedField("083", "Fisheries", "การประมง"),
    IscedField("084", "Veterinary", "สัตวแพทยศาสตร์"),
    IscedField("091", "Health", "สาธารณสุขศาสตร์"),
    IscedField("092", "Welfare", "สวัสดิการสังคม"),
    IscedField("101", "Personal services", "การบริการส่วนบุคคล"),
    IscedField("102", "Hygiene and occupational health services", "สุขอนามัยและอาชีวอนามัย"),
    IscedField("103", "Security services", "การรักษาความปลอดภัย"),
    IscedField("104", "Transport services", "การขนส่ง"),
]

DETAILED_FIELDS: list[IscedField] = [
    IscedField("0011", "Basic programmes and qualifications", "หลักสูตรพื้นฐานทั่วไป"),
    IscedField("0021", "Literacy and numeracy", "การรู้หนังสือและการคำนวณ"),
    IscedField("0031", "Personal skills and development", "ทักษะและการพัฒนาส่วนบุคคล"),
    IscedField("0111", "Education science", "ศึกษาศาสตร์"),
    IscedField("0112", "Training for pre-school teachers", "การฝึกหัดครูปฐมวัย"),
    IscedField(
        "0113",
        "Teacher training without subject specialisation",
        "การฝึกหัดครูไม่ระบุสาขาวิชาเฉพาะ",
    ),
    IscedField("0114", "Teacher training with subject specialisation", "การฝึกหัดครูระบุสาขาวิชาเฉพาะ"),
    IscedField("0210", "Arts, not further defined", "ศิลปกรรมศาสตร์ (ไม่ระบุเฉพาะ)"),
    IscedField("0211", "Audio-visual techniques and media production", "เทคนิคโสตทัศน์และการผลิตสื่อ"),
    IscedField(
        "0212",
        "Fashion, interior and industrial design",
        "แฟชั่น การออกแบบภายใน และการออกแบบอุตสาหกรรม",
    ),
    IscedField("0213", "Fine arts", "วิจิตรศิลป์"),
    IscedField("0214", "Handicrafts", "หัตถกรรม"),
    IscedField("0215", "Music and performing arts", "ดนตรีและศิลปะการแสดง"),
    IscedField("0221", "Religion and theology", "ศาสนาและเทววิทยา"),
    IscedField("0222", "History and archaeology", "ประวัติศาสตร์และโบราณคดี"),
    IscedField("0223", "Philosophy and ethics", "ปรัชญาและจริยศาสตร์"),
    IscedField("0231", "Language acquisition", "การเรียนรู้ภาษา"),
    IscedField("0232", "Literature and linguistics", "วรรณคดีและภาษาศาสตร์"),
    IscedField("0311", "Economics", "เศรษฐศาสตร์"),
    IscedField("0312", "Political sciences and civics", "รัฐศาสตร์และพลเมืองศึกษา"),
    IscedField("0313", "Psychology", "จิตวิทยา"),
    IscedField("0314", "Sociology and cultural studies", "สังคมวิทยาและวัฒนธรรมศึกษา"),
    IscedField("0321", "Journalism and reporting", "วารสารศาสตร์และการรายงานข่าว"),
    IscedField(
        "0322",
        "Library, information and archival studies",
        "บรรณารักษศาสตร์ สารสนเทศศาสตร์ และจดหมายเหตุ",
    ),
    IscedField(
        "0410",
        "Business and administration, not further defined",
        "บริหารธุรกิจและการจัดการ (ไม่ระบุเฉพาะ)",
    ),
    IscedField("0411", "Accounting and taxation", "การบัญชีและภาษีอากร"),
    IscedField("0412", "Finance, banking and insurance", "การเงิน การธนาคาร และการประกันภัย"),
    IscedField("0413", "Management and administration", "การจัดการและการบริหาร"),
    IscedField("0414", "Marketing and advertising", "การตลาดและการโฆษณา"),
    IscedField("0415", "Secretarial and office work", "งานเลขานุการและงานสำนักงาน"),
    IscedField("0416", "Wholesale and retail sales", "การขายส่งและการขายปลีก"),
    IscedField("0417", "Work skills", "ทักษะการทำงาน"),
    IscedField("0421", "Law", "นิติศาสตร์"),
    IscedField("0511", "Biology", "ชีววิทยา"),
    IscedField("0512", "Biochemistry", "ชีวเคมี"),
    IscedField("0521", "Environmental sciences", "วิทยาศาสตร์สิ่งแวดล้อม"),
    IscedField("0522", "Natural environments and wildlife", "สิ่งแวดล้อมธรรมชาติและสัตว์ป่า"),
    IscedField("0531", "Chemistry", "เคมี"),
    IscedField("0532", "Earth sciences", "วิทยาศาสตร์โลก"),
    IscedField("0533", "Physics", "ฟิสิกส์"),
    IscedField("0541", "Mathematics", "คณิตศาสตร์"),
    IscedField("0542", "Statistics", "สถิติ"),
    IscedField("0611", "Computer use", "การใช้คอมพิวเตอร์"),
    IscedField(
        "0612",
        "Database and network design and administration",
        "การออกแบบและบริหารฐานข้อมูลและเครือข่าย",
    ),
    IscedField(
        "0613",
        "Software and applications development and analysis",
        "การพัฒนาและวิเคราะห์ซอฟต์แวร์และแอปพลิเคชัน",
    ),
    IscedField(
        "0710",
        "Engineering and engineering trades, not further defined",
        "วิศวกรรมศาสตร์และช่างเทคนิควิศวกรรม (ไม่ระบุเฉพาะ)",
    ),
    IscedField("0711", "Chemical engineering and processes", "วิศวกรรมเคมีและกระบวนการ"),
    IscedField("0712", "Environmental protection technology", "เทคโนโลยีการป้องกันสิ่งแวดล้อม"),
    IscedField("0713", "Electricity and energy", "ไฟฟ้าและพลังงาน"),
    IscedField("0714", "Electronics and automation", "อิเล็กทรอนิกส์และระบบอัตโนมัติ"),
    IscedField("0715", "Mechanics and metal trades", "เครื่องกลและช่างโลหะ"),
    IscedField("0716", "Motor vehicles, ships and aircraft", "ยานยนต์ เรือ และอากาศยาน"),
    IscedField("0721", "Food processing", "การแปรรูปอาหาร"),
    IscedField(
        "0722",
        "Materials (glass, paper, plastic and wood)",
        "วัสดุศาสตร์ (แก้ว กระดาษ พลาสติก และไม้)",
    ),
    IscedField(
        "0723",
        "Textiles (clothes, footwear and leather)",
        "สิ่งทอ (เสื้อผ้า รองเท้า และเครื่องหนัง)",
    ),
    IscedField("0724", "Mining and extraction", "การทำเหมืองแร่และการสกัด"),
    IscedField("0731", "Architecture and town planning", "สถาปัตยกรรมศาสตร์และผังเมือง"),
    IscedField("0732", "Building and civil engineering", "วิศวกรรมโยธาและการก่อสร้าง"),
    IscedField("0811", "Crop and livestock production", "การผลิตพืชและปศุสัตว์"),
    IscedField("0812", "Horticulture", "พืชสวน"),
    IscedField("0821", "Forestry", "วนศาสตร์"),
    IscedField("0831", "Fisheries", "การประมง"),
    IscedField("0841", "Veterinary", "สัตวแพทยศาสตร์"),
    IscedField("0911", "Dental studies", "ทันตแพทยศาสตร์"),
    IscedField("0912", "Medicine", "แพทยศาสตร์"),
    IscedField("0913", "Nursing and midwifery", "พยาบาลศาสตร์และผดุงครรภ์"),
    IscedField(
        "0914",
        "Medical diagnostic and treatment technology",
        "เทคโนโลยีการวินิจฉัยและบำบัดทางการแพทย์",
    ),
    IscedField("0915", "Therapy and rehabilitation", "กายภาพบำบัดและการฟื้นฟูสมรรถภาพ"),
    IscedField("0916", "Pharmacy", "เภสัชศาสตร์"),
    IscedField(
        "0917",
        "Traditional and complementary medicine and therapy",
        "การแพทย์แผนไทยและการแพทย์ทางเลือก",
    ),
    IscedField("0921", "Care of the elderly and of disabled adults", "การดูแลผู้สูงอายุและผู้พิการ"),
    IscedField("0922", "Child care and youth services", "การดูแลเด็กและบริการเยาวชน"),
    IscedField("0923", "Social work and counselling", "สังคมสงเคราะห์และการให้คำปรึกษา"),
    IscedField("1011", "Domestic services", "งานบริการในครัวเรือน"),
    IscedField("1012", "Hair and beauty services", "การเสริมสวยและความงาม"),
    IscedField("1013", "Hotel, restaurants and catering", "โรงแรม ภัตตาคาร และการจัดเลี้ยง"),
    IscedField("1014", "Sports", "การกีฬา"),
    IscedField("1015", "Travel, tourism and leisure", "การท่องเที่ยวและนันทนาการ"),
    IscedField("1021", "Community sanitation", "สุขาภิบาลชุมชน"),
    IscedField("1022", "Occupational health and safety", "อาชีวอนามัยและความปลอดภัย"),
    IscedField("1031", "Military and defence", "การทหารและการป้องกันประเทศ"),
    IscedField("1032", "Protection of persons and property", "การคุ้มครองบุคคลและทรัพย์สิน"),
    IscedField("1041", "Transport services", "การขนส่ง"),
]

_DETAILED_BY_CODE: dict[str, IscedField] = {f.code: f for f in DETAILED_FIELDS}


def get_detailed_field(code: str) -> IscedField | None:
    return _DETAILED_BY_CODE.get(code)


def all_detailed_fields() -> list[IscedField]:
    return DETAILED_FIELDS
