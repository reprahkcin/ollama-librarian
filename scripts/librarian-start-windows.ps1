param(
  [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot),
  [string]$LibraryDir = "$HOME\Documents\LLM Library",
  [string]$StateDir = "$env:APPDATA\ollama-librarian"
)

$ErrorActionPreference = 'Stop'
$RunDir = Join-Path $StateDir 'run'
$LogDir = Join-Path $StateDir 'logs'
$OllamaPidFile = Join-Path $RunDir 'ollama.pid'
$WebPidFile = Join-Path $RunDir 'web.pid'
$PythonBin = Join-Path $RepoDir '.venv\Scripts\python.exe'

New-Item -ItemType Directory -Path $LibraryDir -Force | Out-Null
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

if (!(Test-Path $PythonBin)) {
  Write-Error "Missing Python venv at $PythonBin. Run Setup Guides/WINDOWS-SETUP.md first."
}

function Test-Http($Url) {
  try {
    $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
    return $true
  } catch {
    return $false
  }
}

if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) {
  Write-Host 'Starting Ollama...'
  $ollamaCmd = 'set OLLAMA_HOST=127.0.0.1:11434&& ollama serve'
  $ollamaProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $ollamaCmd -WindowStyle Hidden -PassThru
  $ollamaProc.Id | Out-File -FilePath $OllamaPidFile -Encoding ascii -Force
}

for ($i=0; $i -lt 30; $i++) {
  if (Test-Http 'http://127.0.0.1:11434/api/tags') { break }
  Start-Sleep -Seconds 1
}
if (-not (Test-Http 'http://127.0.0.1:11434/api/tags')) {
  Write-Error 'Ollama did not become ready.'
}

if (-not (Test-Http 'http://127.0.0.1:8088/api/pdf/status')) {
  Write-Host 'Starting web app...'
  $webScript = Join-Path $RepoDir 'scripts\ollama-web-chat.py'
  $webCmd = @(
    'set OLLAMA_WEB_HOST=127.0.0.1',
    'set OLLAMA_WEB_PORT=8088',
    'set OLLAMA_BASE_URL=http://127.0.0.1:11434',
    ('set OLLAMA_WEB_PDF_SOURCE=' + $LibraryDir),
    ('set OLLAMA_WEB_PDF_INDEX_DB=' + (Join-Path $StateDir 'pdf-rag.sqlite')),
    ('set OLLAMA_WEB_HISTORY_PATH=' + (Join-Path $StateDir 'ollama-web-chat-history.json')),
    ('set OLLAMA_WEB_STASH_PATH=' + (Join-Path $StateDir 'ollama-response-stash.json')),
    'set OLLAMA_WEB_PDF_OCR_ON_SYNC=1',
    'set OLLAMA_WEB_PDF_OCR_LANG=eng',
    'set OLLAMA_WEB_PDF_OCR_JOBS=4',
    'set OLLAMA_WEB_PDF_OCR_TIMEOUT=3600',
    ('"' + $PythonBin + '" "' + $webScript + '"')
  ) -join '&& '
  $webProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $webCmd -WindowStyle Hidden -PassThru
  $webProc.Id | Out-File -FilePath $WebPidFile -Encoding ascii -Force
}

for ($i=0; $i -lt 30; $i++) {
  if (Test-Http 'http://127.0.0.1:8088/api/pdf/status') { break }
  Start-Sleep -Seconds 1
}

if (Test-Http 'http://127.0.0.1:8088/api/pdf/status') {
  Write-Host 'Librarian is running at http://127.0.0.1:8088'
} else {
  Write-Error 'Web app did not become ready.'
}
