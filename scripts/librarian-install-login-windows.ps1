param(
  [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot)
)

$TaskName = 'OllamaLibrarianStartup'
$StartScript = Join-Path $RepoDir 'scripts\librarian-start-windows.ps1'
$Action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$StartScript`""

schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
schtasks /Create /SC ONLOGON /RL LIMITED /TN $TaskName /TR $Action /F | Out-Null
Write-Host "Installed startup task: $TaskName"
