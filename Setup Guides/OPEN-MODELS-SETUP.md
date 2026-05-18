# Open Models Setup Guide (Ollama Librarian)

## Goal

Install additional open/free models in Ollama so they appear in Ollama Librarian and can be used for chat and PDF-grounded workflows.

This guide is additive. It does not replace your platform setup guide:

- [MAC-SETUP.md](MAC-SETUP.md)
- [LINUX-SETUP.md](LINUX-SETUP.md)
- [WINDOWS-SETUP.md](WINDOWS-SETUP.md)

## Before You Start

- Ollama is installed and running on `127.0.0.1:11434`
- You already completed your OS setup guide
- Your web UI runs at `http://127.0.0.1:8088`

Quick check:

```bash
curl http://127.0.0.1:11434/api/tags
```

PowerShell equivalent:

```powershell
curl http://127.0.0.1:11434/api/tags
```

## Recommended Open Model Packs

Choose one or more packs based on your hardware.

### Pack A: Fast + Lower Memory

- `llama3.2:3b`
- `qwen2.5:3b`
- `nomic-embed-text`

### Pack B: Balanced General Use

- `llama3.1:8b`
- `mistral:7b`
- `qwen2.5:7b`
- `nomic-embed-text`

### Pack C: Higher Quality (More RAM/VRAM)

- `qwen2.5:14b`
- `gemma2:9b`
- `llama3.1:8b`
- `nomic-embed-text`

## Install Commands

Run the commands for your shell.

### macOS / Linux (bash)

Pack B example:

```bash
ollama pull llama3.1:8b
ollama pull mistral:7b
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Pack C example:

```bash
ollama pull qwen2.5:14b
ollama pull gemma2:9b
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### Windows (PowerShell)

Pack B example:

```powershell
ollama pull llama3.1:8b
ollama pull mistral:7b
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Pack C example:

```powershell
ollama pull qwen2.5:14b
ollama pull gemma2:9b
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

## Verify Installed Models

List what is installed:

```bash
ollama list
```

PowerShell:

```powershell
ollama list
```

API check:

```bash
curl http://127.0.0.1:11434/api/tags
```

## Quick Model Smoke Tests

Test one model directly with Ollama:

```bash
ollama run llama3.1:8b "Write a 3-bullet summary of why citations matter in research answers."
```

PowerShell:

```powershell
ollama run llama3.1:8b "Write a 3-bullet summary of why citations matter in research answers."
```

## Use New Models In Ollama Librarian

In the web UI:

1. Open `http://127.0.0.1:8088`
2. Click Refresh next to the model dropdown
3. Select any newly pulled model
4. Keep Use PDF-grounded answers enabled for citation-backed output

## CLI Snippets With Different Answer Models

You can test answer quality per model from CLI while keeping the same embedding model.

macOS / Linux:

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate

python scripts/pdf_library_rag.py \
  --ollama-base http://127.0.0.1:11434 \
  --index-db "$HOME/Library/Application Support/ollama-librarian/pdf-rag.sqlite" \
  ask --query "Summarize the key findings with citation markers." \
  --answer-model llama3.1:8b \
  --embed-model nomic-embed-text \
  --top-k 6
```

Windows PowerShell:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\.venv\Scripts\Activate.ps1

python scripts\pdf_library_rag.py `
  --ollama-base http://127.0.0.1:11434 `
  --index-db "$env:APPDATA\ollama-librarian\pdf-rag.sqlite" `
  ask --query "Summarize the key findings with citation markers." `
  --answer-model llama3.1:8b `
  --embed-model nomic-embed-text `
  --top-k 6
```

## Switching Models Safely

- Keep `nomic-embed-text` stable for indexing/query consistency.
- Re-index only if you intentionally change embedding model.
- Compare models on the same prompt before deciding your default.

## Optional: Remove Models You Do Not Need

```bash
ollama rm <model-name>
```

PowerShell:

```powershell
ollama rm <model-name>
```

Example:

```bash
ollama rm llama3.2:3b
```

## Troubleshooting

If a model pull fails:

1. Check Ollama is running: `ollama list`
2. Retry the pull command
3. Confirm model tag spelling
4. Refresh model list in the web UI

If the model is not shown in the UI:

1. Confirm it appears in `ollama list`
2. Click Refresh in the model row
3. Restart the web UI using your platform start script
