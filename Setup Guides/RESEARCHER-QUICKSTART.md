# Researcher Quick Start (Minimal Daily Workflow)

This guide is for non-technical users after initial setup is complete.

Default access model:

- The normal workflow is local-only on the same machine (`http://127.0.0.1:8088`).
- Network/LAN access is intentionally unsupported.

## What You Do Each Day

1. Start the system
2. Open the web page
3. Ask questions
4. Sync new documents when needed
5. Stop the system when done

## macOS Daily Use

Start and open:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-macos.sh
./scripts/librarian-open-ui-macos.sh
```

Stop:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-stop-macos.sh
```

Status check:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-status-macos.sh
```

## Windows Daily Use (PowerShell)

Start and open:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-start-windows.ps1
.\scripts\librarian-open-ui-windows.ps1
```

Stop:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-stop-windows.ps1
```

Status check:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-status-windows.ps1
```

## Syncing New Documents

1. Copy files into your library folder.
2. Open the web page.
3. Enable Use PDF-grounded answers.
4. Click Sync New PDFs.

Optional in-UI upload flow:

1. Open the web page.
2. Click Upload Documents.
3. Select one or more supported files.
4. The app uploads files into your configured library path; then click Sync New PDFs (or wait if auto-sync is started).

Supported file types:

- .pdf
- .txt
- .md
- .html
- .htm
- .epub

## Optional: Start Automatically at Login

macOS:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-install-login-macos.sh
```

Windows:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-install-login-windows.ps1
```

## Resource Behavior (Simple)

- When stopped, it uses no resources.
- When running idle, CPU should be low.
- Memory usage can stay elevated for a while after model use.
