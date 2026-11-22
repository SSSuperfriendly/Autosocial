$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

# Kill any existing process on port 8000
$existing = netstat -ano | Select-String ":8000\s+\S+\s+LISTENING" | ForEach-Object {
  ($_ -split '\s+')[-1]
} | Select-Object -First 1
if ($existing) {
  Write-Host "Stopping existing process on port 8000 (PID $existing)..." -ForegroundColor Yellow
  Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 500
}

Write-Host "Building frontend..." -ForegroundColor Cyan
Set-Location "$root\frontend"
npm run build
if ($LASTEXITCODE -ne 0) {
  throw "Frontend build failed."
}

Write-Host "Starting product server at http://127.0.0.1:8000 ..." -ForegroundColor Green
Set-Location $root
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
