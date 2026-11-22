$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$existing = netstat -ano | Select-String ":8000\s+\S+\s+LISTENING" | ForEach-Object {
  ($_ -split '\s+')[-1]
} | Select-Object -First 1
if ($existing) {
  Write-Host "Stopping existing process on port 8000 (PID $existing)..." -ForegroundColor Yellow
  Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 500
}

Set-Location $root
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
