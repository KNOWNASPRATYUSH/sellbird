# Start Sellbird Dashboard and Cloudflare Tunnel with full link & clipboard copy
$ErrorActionPreference = "Continue"

Write-Host "Starting Sellbird Dashboard & Cloudflare Tunnel..." -ForegroundColor Cyan

# 1. Read the private dashboard token
$tokenPath = "data\dashboard-token"
if (-not (Test-Path $tokenPath)) {
    Write-Host "Initializing dashboard to create token..." -ForegroundColor Yellow
    & ".\.venv\Scripts\sellbird.exe" dashboard --url | Out-Null
}
$token = (Get-Content $tokenPath -Raw).Trim()

# 2. Check if dashboard server is already running on port 5555
$dashboardRunning = Test-NetConnection -ComputerName 127.0.0.1 -Port 5555 -InformationLevel Quiet
if (-not $dashboardRunning) {
    Write-Host "Starting local Sellbird dashboard in background..." -ForegroundColor Yellow
    Start-Process -FilePath ".\.venv\Scripts\sellbird.exe" -ArgumentList "dashboard" -WindowStyle Hidden
    Start-Sleep -Seconds 2
} else {
    Write-Host "Local Sellbird dashboard is already running on port 5555." -ForegroundColor Green
}

# 3. Launch Cloudflare Tunnel and display the combined link
Write-Host "Connecting Cloudflare Tunnel..." -ForegroundColor Yellow
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

& $cloudflared tunnel --url http://localhost:5555 --http-host-header localhost:5555 2>&1 | ForEach-Object {
    $line = $_.ToString()
    if ($line -match "(https://[a-zA-Z0-9-]+\.trycloudflare\.com)") {
        $tunnelUrl = $matches[1]
        $fullLink = "$tunnelUrl/#token=$token"
        Write-Host ""
        Write-Host "==================================================================" -ForegroundColor Green
        Write-Host " YOUR LIVE SELLBIRD LINK (Phone & PC):" -ForegroundColor Green
        Write-Host " $fullLink" -ForegroundColor Yellow
        Write-Host "==================================================================" -ForegroundColor Green
        try {
            Set-Clipboard -Value $fullLink
            Write-Host "(Copied to your clipboard automatically!)" -ForegroundColor Gray
        } catch {}
        Write-Host ""
    }
    Write-Host $line
}
