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

if [[ ! "$BRANCH" =~ ^[A-Za-z0-9._/-]{1,128}$ ]]; then
  echo "invalid branch name: $BRANCH" >&2
  exit 2
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  echo "refusing update: current branch is '$CURRENT_BRANCH' (expected '$BRANCH')" >&2
  exit 3
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing update: working tree is dirty" >&2
  exit 4
fi

if ! git ls-remote --exit-code origin "refs/heads/$BRANCH" >/dev/null 2>&1; then
  echo "refusing update: origin branch not found: $BRANCH" >&2
  exit 5
fi

echo "update-script: fetch origin/$BRANCH"
git fetch origin -- "$BRANCH"

echo "update-script: pull --ff-only origin/$BRANCH"
git pull --ff-only origin -- "$BRANCH"

echo "update-script: completed"
