[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ไม่พบ Docker — ติดตั้ง Docker Desktop ก่อน" -ForegroundColor Red
    exit 1
}

Write-Host "คำเตือน: การรีเซ็ตจะลบข้อมูลทั้งหมดที่คุณสร้างหรือแก้ไขไว้ในระบบ" -ForegroundColor Yellow
Write-Host "แล้วคืนค่ากลับเป็นตัวอย่างชุดเดิมที่มากับโปรแกรม ข้อมูลที่ลบแล้วกู้คืนไม่ได้" -ForegroundColor Yellow
$answer = Read-Host "ต้องการลบงานของคุณและเริ่มใหม่ใช่หรือไม่? พิมพ์ y แล้วกด Enter เพื่อยืนยัน (อย่างอื่น = ยกเลิก)"
if ($answer -ne "y") {
    Write-Host "ยกเลิกการรีเซ็ต ข้อมูลของคุณไม่ถูกเปลี่ยนแปลง"
    exit 0
}

docker compose down -v
if ($LASTEXITCODE -ne 0) {
    Write-Host "รีเซ็ตไม่สำเร็จ กรุณาตรวจสอบว่า Docker Desktop ทำงานอยู่ แล้วลองอีกครั้ง" -ForegroundColor Red
    exit 1
}

& "$PSScriptRoot\start.ps1"
exit $LASTEXITCODE
