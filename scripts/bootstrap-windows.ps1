param(
  [string]$RepoDir = "$HOME\GIT\ollama-librarian",
  [string]$LibraryDir = "$HOME\Documents\LLM Library",
  [string]$StateDir = "$env:APPDATA\ollama-librarian"
)

$ErrorActionPreference = 'Stop'

winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id Ollama.Ollama -e

New-Item -ItemType Directory -Path $LibraryDir -Force | Out-Null
New-Item -ItemType Directory -Path $StateDir -Force | Out-Null

Set-Location $RepoDir
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r scripts\pdf-rag-requirements.txt

Write-Host "Bootstrap complete."
Write-Host "Library path: $LibraryDir"
Write-Host "State path: $StateDir"
Write-Host "Next: start Ollama (set OLLAMA_HOST=127.0.0.1:11434; ollama serve) and run scripts\ollama-web-chat.py"
