[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location $PSScriptRoot

function Fail([string]$message) {
    Write-Host ""
    Write-Host $message -ForegroundColor Red
    exit 1
}

# Simple KEY=VALUE parse; blank lines and comments are ignored.
$envVars = @{}
if (-not (Test-Path ".env")) {
    Fail "ไม่พบไฟล์ .env ในโฟลเดอร์นี้ กรุณาใช้ไฟล์ชุดติดตั้งที่ได้รับมาให้ครบทุกไฟล์"
}
foreach ($line in Get-Content -Encoding UTF8 ".env") {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    $eq = $trimmed.IndexOf("=")
    if ($eq -lt 1) { continue }
    $envVars[$trimmed.Substring(0, $eq).Trim()] = $trimmed.Substring($eq + 1).Trim()
}
# A value already set in the shell beats .env for compose interpolation; the
# package's own .env must win.
foreach ($name in "APP_PORT", "APP_IMAGE", "COMPOSE_PROJECT_NAME", "POSTGRES_PASSWORD") {
    if ($envVars.ContainsKey($name)) { Set-Item -Path "Env:$name" -Value $envVars[$name] }
}


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
