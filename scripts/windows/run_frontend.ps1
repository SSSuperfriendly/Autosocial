$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location "$root\frontend"
npm run dev
