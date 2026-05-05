param(
  [string]$StateDir = "$env:APPDATA\ollama-librarian"
)

$ErrorActionPreference = 'SilentlyContinue'
$RunDir = Join-Path $StateDir 'run'
$OllamaPidFile = Join-Path $RunDir 'ollama.pid'
$WebPidFile = Join-Path $RunDir 'web.pid'

function Stop-FromPidFile($Path) {
  if (Test-Path $Path) {
    $pid = Get-Content $Path | Select-Object -First 1
    if ($pid) { Stop-Process -Id $pid -Force }
    Remove-Item $Path -Force
  }
}

Stop-FromPidFile $WebPidFile
Stop-FromPidFile $OllamaPidFile

Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'ollama-web-chat.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'ollama serve' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host 'Stopped.'
