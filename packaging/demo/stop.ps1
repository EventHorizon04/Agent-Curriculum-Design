[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ไม่พบ Docker — ติดตั้ง Docker Desktop ก่อน" -ForegroundColor Red
    exit 1
}

Write-Host "กำลังหยุดระบบ (ข้อมูลของคุณยังอยู่ครบ)..."
docker compose down
if ($LASTEXITCODE -ne 0) {
    Write-Host "หยุดระบบไม่สำเร็จ กรุณาตรวจสอบว่า Docker Desktop ทำงานอยู่ แล้วลองอีกครั้ง" -ForegroundColor Red
    exit 1
}
Write-Host "หยุดระบบแล้ว เริ่มใหม่ได้ด้วย start.cmd" -ForegroundColor Green
exit 0
