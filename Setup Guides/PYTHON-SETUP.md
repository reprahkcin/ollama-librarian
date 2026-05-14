# Python Setup Guide (Mac + Windows + Linux)

Use this guide when setting up Ollama Librarian for the first time, or when Python/venv commands fail.

## Required Version

- Python 3.10 or newer

## Quick Verification

Run these in a terminal:

macOS:

```bash
python3 --version
python3 -m pip --version
```

Windows PowerShell:

```powershell
py --version
py -m pip --version
```

Linux:

```bash
python3 --version
python3 -m pip --version
```

If either command fails, install Python first using the steps below.

## Install Python (macOS)

```bash
brew update
brew install python
python3 --version
```

## Install Python (Windows)

Open PowerShell as Administrator:

```powershell
winget install --id Python.Python.3.12 -e
```

Then close and reopen PowerShell:

```powershell
py --version
```

## Install Python (Linux)

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 --version
```

Fedora:

```bash
sudo dnf install -y python3 python3-pip python3-virtualenv
python3 --version
```

## Create the Virtual Environment

macOS:

```bash
cd ~/GIT/ollama-librarian
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r scripts/pdf-rag-requirements.txt
```

Windows PowerShell:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r scripts\pdf-rag-requirements.txt
```

Linux:

```bash
cd ~/GIT/ollama-librarian
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r scripts/pdf-rag-requirements.txt
```

## Confirm It Worked

macOS:

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate
python --version
python -m pip list | grep -E "pypdf|ebooklib"
```

Windows PowerShell:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\.venv\Scripts\Activate.ps1
python --version
python -m pip list | Select-String "pypdf|ebooklib"
```

Linux:

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate
python --version
python -m pip list | grep -E "pypdf|ebooklib"
```

## Common Fixes

### pip not found

macOS:

```bash
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade pip
```

Windows:

```powershell
py -m ensurepip --upgrade
py -m pip install --upgrade pip
```

Linux:

```bash
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade pip
```

### PowerShell blocks Activate.ps1

Run this once in PowerShell:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Wrong Python selected

Use explicit executables:

macOS:

```bash
/usr/bin/python3 -m venv .venv
```

Windows:

```powershell
py -3 -m venv .venv
```

Linux:

```bash
/usr/bin/python3 -m venv .venv
```

## Next Step

After Python setup succeeds, return to:

- [MAC-SETUP.md](MAC-SETUP.md)
- [LINUX-SETUP.md](LINUX-SETUP.md)
- [WINDOWS-SETUP.md](WINDOWS-SETUP.md)
- [RESEARCHER-QUICKSTART.md](RESEARCHER-QUICKSTART.md)
