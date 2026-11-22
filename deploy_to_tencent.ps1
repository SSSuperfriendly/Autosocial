param(
  [Parameter(Mandatory = $true)]
  [string]$HostName,
  [string]$User = "ubuntu",
  [Parameter(Mandatory = $true)]
  [string]$KeyPath,
  [string]$RepoUrl = "",
  [string]$Branch = "main",
  [string]$CommitMessage = "",
  [switch]$SkipCommit,
  [switch]$SkipLocalChecks,
  [switch]$SkipPush
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $RepoUrl) { $RepoUrl = (git -C $root remote get-url origin).Trim() }

function Run-Step([string]$Name, [scriptblock]$Block) {
  Write-Host ""
  Write-Host "== $Name ==" -ForegroundColor Cyan
  & $Block
}

if (-not (Test-Path -LiteralPath $KeyPath)) {
  throw "SSH key not found: $KeyPath"
}

Run-Step "Check Git repository" {
  Set-Location $root
  if (-not (Test-Path -LiteralPath (Join-Path $root ".git"))) {
    throw "This directory is not a Git repository. Run git init and push the initial code first."
  }
  git remote get-url origin | Out-Null
}

if (-not $SkipLocalChecks) {
  Run-Step "Build frontend" {
    Push-Location (Join-Path $root "frontend")
    npm run build
    Pop-Location
  }

  Run-Step "Compile Python" {
    python -m compileall autosocial server
  }
}

if (-not $SkipCommit) {
  Run-Step "Commit local changes" {
    Set-Location $root
    git add -A
    $staged = git diff --cached --name-only
    if (-not $staged) {
      Write-Host "No local changes to commit."
      return
    }

    $message = $CommitMessage.Trim()
    if (-not $message) {
      $message = "Update AutoSocial"
    }
    git commit -m $message
  }
}

if (-not $SkipPush) {
  Run-Step "Push to GitHub" {
    $dirty = git status --porcelain
    if ($dirty) {
      $dirty
      throw "Working tree has uncommitted changes. Commit them before deploying, or rerun without -SkipCommit."
    }
    git push origin $Branch
  }
}

Run-Step "Update server from GitHub" {
  $remoteCommand = @"
set -e
export AUTOSOCIAL_REPO_URL='$RepoUrl'
export AUTOSOCIAL_BRANCH='$Branch'
sudo -E bash /opt/autosocial/app/deploy/scripts/deploy_update.sh
"@
  ssh -i $KeyPath -o BatchMode=yes "$User@$HostName" $remoteCommand
}

Run-Step "Verify public site" {
  $healthUrl = "http://$HostName/health"
  $ok = $false
  for ($i = 1; $i -le 12; $i++) {
    $body = ""
    $exitCode = 1
    try {
      $body = curl.exe -fsS -L --max-time 10 $healthUrl 2>$null
      $exitCode = $LASTEXITCODE
    } catch {
      $exitCode = $LASTEXITCODE
    }
    if ($exitCode -eq 0 -and $body -match '"ok"\s*:\s*true') {
      Write-Host $body
      $ok = $true
      break
    }
    Start-Sleep -Seconds 2
  }
  if (-not $ok) {
    throw "Public health check failed: $healthUrl"
  }
  Write-Host "Public URL: http://$HostName" -ForegroundColor Green
}
