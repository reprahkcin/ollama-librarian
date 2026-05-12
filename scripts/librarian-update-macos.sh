#!/usr/bin/env bash
set -euo pipefail

# Applies updates by fast-forwarding the selected branch from origin.
# Prints status lines for the caller and exits non-zero on failure.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      if [[ $# -lt 2 ]]; then
        echo "missing value for --branch" >&2
        exit 2
      fi
      BRANCH="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--branch <branch>]"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

cd "$ROOT_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required but not found" >&2
  exit 1
fi

echo "update-script: fetch origin/$BRANCH"
git fetch origin "$BRANCH"

echo "update-script: pull --ff-only origin/$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "update-script: completed"
