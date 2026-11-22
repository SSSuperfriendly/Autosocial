param(
  [Parameter(Mandatory = $true)]
  [string]$SshHost,
  [string]$HealthUrl = "",
  [string]$Message = "",
  [switch]$SkipBuild,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$SSH_HOST = $SshHost
$REMOTE_DEPLOY = "sudo bash /opt/autosocial/app/deploy/scripts/deploy_update.sh"

function Step([string]$label) {
  Write-Host "`n=== $label ===" -ForegroundColor Cyan
}

function Check([string]$label) {
  if ($LASTEXITCODE -ne 0) { throw "FAILED: $label (exit $LASTEXITCODE)" }
  Write-Host "[OK] $label" -ForegroundColor Green
}

# ── 1. Pre-flight: check uncommitted changes ───────────────────────────────
Step "Pre-flight"
Set-Location $root

$status = git status --porcelain
if ($status -and $DryRun) {
  Write-Host "[DRY-RUN] would commit local changes; no files staged or committed."
} elseif ($status) {
  if (-not $Message) {
    Write-Host "Uncommitted changes detected:" -ForegroundColor Yellow
    git status --short
    $Message = Read-Host "Commit message (leave blank to abort)"
    if (-not $Message) { throw "Aborted: no commit message." }
  }
  git add -A
  git commit -m $Message
  Check "git commit"
} else {
  Write-Host "[OK] Working tree clean" -ForegroundColor Green
}

# ── 2. Push to GitHub ─────────────────────────────────────────────────────
Step "Push to GitHub"
if ($DryRun) { Write-Host "[DRY-RUN] would: git push origin main" }
else {
  git push origin main
  Check "git push"
}

# ── 3. Remote deploy ──────────────────────────────────────────────────────
Step "Deploy to server ($SSH_HOST)"
if ($DryRun) {
  Write-Host "[DRY-RUN] would ssh $SSH_HOST '$REMOTE_DEPLOY'"
} else {
  ssh $SSH_HOST $REMOTE_DEPLOY
  Check "remote deploy"
}

# ── 4. Smoke test ─────────────────────────────────────────────────────────
Step "Smoke test (GET /health)"
if (-not $DryRun -and $HealthUrl) {
  Start-Sleep -Seconds 3
  try {
    $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 10
    Write-Host "[OK] Health endpoint responding" -ForegroundColor Green
  } catch {
    Write-Host "[WARN] Smoke test failed: $_" -ForegroundColor Yellow
    Write-Host "       Check: ssh $SSH_HOST 'sudo systemctl status autosocial'"
  }
}

Write-Host "`nDeploy complete." -ForegroundColor Green
