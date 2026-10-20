[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$HealthTimeoutSeconds = 300

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
$port = $envVars["APP_PORT"]
$appImage = $envVars["APP_IMAGE"]
$projectName = $envVars["COMPOSE_PROJECT_NAME"]
if (-not $port -or -not $appImage -or -not $projectName) {
    Fail "ไฟล์ .env ไม่ครบถ้วน กรุณาใช้ไฟล์ชุดติดตั้งที่ได้รับมาใหม่"
}
if ($port -notmatch '^\d{2,5}$') {
    Fail "ค่า APP_PORT= ในไฟล์ .env ต้องเป็นตัวเลข 2-5 หลัก เช่น 8765 กรุณาแก้ไขบรรทัด APP_PORT= แล้วรันใหม่"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "ไม่พบ Docker — ติดตั้ง Docker Desktop ก่อน"
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "เปิด Docker Desktop แล้วรอจนขึ้นว่า running จากนั้นรันใหม่"
}

# Skip the port check when this package's own app is already up (a re-run).
$running = docker ps --filter "label=com.docker.compose.project=$projectName" --filter "label=com.docker.compose.service=app" --format "{{.ID}}"
if (-not $running) {
    $busy = Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue
    if ($busy) {
        Fail "พอร์ต $port ถูกโปรแกรมอื่นใช้อยู่ กรุณาเปิดไฟล์ .env แล้วเปลี่ยนค่า APP_PORT= เป็นเลขอื่น (เช่น 8766) จากนั้นรันใหม่"
    }
}

docker image inspect $appImage *> $null
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path "images.tar")) {
        Fail "ไม่พบไฟล์ images.tar กรุณาใช้ไฟล์ชุดติดตั้งที่ได้รับมาให้ครบทุกไฟล์"
    }
    Write-Host "กำลังติดตั้งโปรแกรมครั้งแรก อาจใช้เวลาหลายนาที กรุณารอสักครู่..."
    docker load -i images.tar
    if ($LASTEXITCODE -ne 0) {
        Fail "โหลดไฟล์ images.tar ไม่สำเร็จ ตรวจสอบว่าพื้นที่ดิสก์เพียงพอและไฟล์ไม่เสียหาย แล้วรันใหม่"
    }
}

Write-Host "กำลังเริ่มระบบ..."
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Fail "เริ่มระบบไม่สำเร็จ กรุณาตรวจสอบว่า Docker Desktop ทำงานอยู่ แล้วรันใหม่ หากยังไม่ได้ (เช่น เคยปิดหน้าต่างระหว่างเริ่มครั้งแรก) ให้รัน reset.cmd เพื่อเริ่มจากตัวอย่างเดิม"
}

$url = "http://127.0.0.1:$port"
$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
$started = Get-Date
$lastReport = $started
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "$url/health"
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        # Not up yet.
    }
    if (((Get-Date) - $lastReport).TotalSeconds -ge 10) {
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        Write-Host "กำลังรอระบบเริ่มทำงาน... ($elapsed วินาที)"
        $lastReport = Get-Date
    }
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    Write-Host ""
    docker compose logs --tail 50 app
    Fail "ระบบยังไม่พร้อมใช้งานภายใน $HealthTimeoutSeconds วินาที กรุณาลองรัน start.cmd อีกครั้ง หากยังไม่ได้ ให้ลองรัน reset.cmd (ข้อมูลที่คุณสร้างไว้จะหายไป) หรือส่งข้อความที่แสดงด้านบนให้ผู้ดูแล"
}

Write-Host ""
Write-Host "ระบบพร้อมใช้งานแล้ว กำลังเปิดเบราว์เซอร์ที่ $url/" -ForegroundColor Green
Start-Process "$url/"
exit 0
