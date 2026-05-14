# Absolute Beginner Daily Guide

Use this after setup is already finished.

You only do two things each day:

1. Start the app.
2. Stop the app when done.

The app opens at <http://127.0.0.1:8088>.

## Quick Help: If You See This, Do This

| If you see this message | What it means | What to do now |
| --- | --- | --- |
| `Librarian is running at http://127.0.0.1:8088` | Everything started correctly | Open your browser to `http://127.0.0.1:8088` |
| `Web app already running.` | The app was already on | Keep going, this is okay |
| `Ollama already running.` | The AI engine was already on | Keep going, this is okay |
| `Web UI: stopped` | The app website is not running | Run the **Start The App** block again |
| `Ollama: stopped` | The AI engine is not running | Run the **Start The App** block again |
| `Missing Python venv ...` | Setup was not completed on this computer | Ask your installer/admin to run setup again |
| `Could not find 'ollama' in PATH` | Ollama is not installed correctly | Ask your installer/admin to reinstall Ollama |
| `Web app did not become ready` | The app tried to start but failed | Run **Check Status** and share the output with support |
| `Ollama did not become ready` | Ollama tried to start but failed | Run **Check Status** and share the output with support |

## First: Open The Command App

If you do not know what a terminal is, use these steps.

macOS:

1. Press Command + Space.
2. Type Terminal.
3. Press Enter.

Windows:

1. Press the Windows key.
2. Type PowerShell.
3. Press Enter.

Linux:

1. Press Ctrl + Alt + T.
2. If that does not open it, open your app menu and search for Terminal.

## Start The App

Pick your computer type. Copy and paste the matching block. Press Enter.

macOS:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-macos.sh
./scripts/librarian-open-ui-macos.sh
```

Windows (PowerShell):

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-start-windows.ps1
.\scripts\librarian-open-ui-windows.ps1
```

Linux:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-linux.sh
./scripts/librarian-open-ui-linux.sh
```

### What You Should See (This Means It Worked)

- `Librarian is running at http://127.0.0.1:8088`:
The app started correctly.
- `Web app already running.`:
The app was already on. This is okay.
- `Ollama already running.`:
The AI engine was already on. This is okay.

### Common Messages (What They Mean)

- `Missing Python venv ... Run Setup Guides/... first.`:
Setup is incomplete. Ask the installer/admin to run setup again.
- `Could not find 'ollama' in PATH`:
Ollama is not installed correctly on this computer.
- `Web app did not become ready. Check .../web.log`:
The app tried to start but failed. Run the Status command below and share the output with support.
- `Ollama did not become ready. Check .../ollama.log`:
The AI engine did not start. Run the Status command below and share the output with support.

## Stop The App

When you are done for the day, copy and paste one block.

macOS:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-stop-macos.sh
```

Windows (PowerShell):

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-stop-windows.ps1
```

Linux:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-stop-linux.sh
```

## If It Does Not Open

Run the status command for your computer type.

macOS:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-status-macos.sh
```

Windows (PowerShell):

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-status-windows.ps1
```

Linux:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-status-linux.sh
```

### How To Read Status Output

- `Ollama: running`:
The AI engine is on.
- `Ollama: stopped`:
The AI engine is off.
- `Web UI: running (http://127.0.0.1:8088)`:
The app website is on and should open in your browser.
- `Web UI: stopped`:
The app website is off. Run the Start block again.

## Add New Documents

1. Put files into your library folder.
2. Open the app page.
3. Turn on Use PDF-grounded answers.
4. Click Sync New PDFs.

You can also click Upload Documents.

Supported file types:

- .pdf
- .txt
- .md
- .html
- .htm
- .epub
