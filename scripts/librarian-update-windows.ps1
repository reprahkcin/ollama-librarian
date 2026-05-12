[CmdletBinding()]
param(
  [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

# Applies updates by fast-forwarding the selected branch from origin.
# Prints status lines for the caller and exits non-zero on failure.

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RootDir

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Error "git is required but not found"
  exit 1
}

if ($Branch -notmatch '^[A-Za-z0-9._/-]{1,128}$') {
  Write-Error "invalid branch name: $Branch"
  exit 2
}

Write-Output "update-script: fetch origin/$Branch"
& git fetch origin -- $Branch
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Output "update-script: pull --ff-only origin/$Branch"
& git pull --ff-only origin -- $Branch
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Output "update-script: completed"
