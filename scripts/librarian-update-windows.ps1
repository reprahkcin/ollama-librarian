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

$currentBranch = (& git rev-parse --abbrev-ref HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
if ($currentBranch -ne $Branch) {
  Write-Error "refusing update: current branch is '$currentBranch' (expected '$Branch')"
  exit 3
}

$statusOut = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
if ($statusOut) {
  Write-Error "refusing update: working tree is dirty"
  exit 4
}

& git ls-remote --exit-code origin "refs/heads/$Branch" | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Error "refusing update: origin branch not found: $Branch"
  exit 5
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
