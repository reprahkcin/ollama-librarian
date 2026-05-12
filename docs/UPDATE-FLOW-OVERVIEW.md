# Update Flow Overview

## Purpose

This document defines the full update feature for Ollama Librarian:

- Detect when a newer release is available.
- Notify researchers in the UI.
- Allow one-click update from within the app.
- Apply repository updates safely with preflight checks and fast-forward sync.

This is the source of truth for implementation behavior.

## Scope

### In Scope

- Versioning and release contract.
- In-app update check and status UI.
- Update apply flow for macOS and Windows.
- Failure handling for preflight and apply operations.

### Out of Scope (Initial MVP)

- Forced updates.
- Auto-updates without user action.
- Linux updater.
- Differential/binary patch updates.
- Artifact download/checksum/rollback installer behavior.

## Guiding Principles

- Safety first: never replace current install without backup.
- Predictable behavior: all update states visible to user.
- Recoverability: explicit failure states and actionable errors.
- Cross-platform parity: same UX on macOS and Windows.
- Minimal trust: only sync from configured repository and branch.

## Versioning Strategy

- Use Semantic Versioning: `vMAJOR.MINOR.PATCH`.
- Current app version comes from a tracked file in-repo.
- Latest version comes from GitHub Release tag.

### Proposed Version Source File

- `scripts/VERSION`

Example:

```text
v1.5.0
```

## High-Level Architecture

### Components

1. App UI (web frontend)

- Shows current version.
- Shows update available state.
- Provides `Check for updates` and `Update now` actions.
- Polls status endpoint while update is running.

2. App API (backend in `scripts/ollama-web-chat.py`)

- `GET /api/update/check`
- `POST /api/update/apply`
- `GET /api/update/status`

3. Platform Updater Scripts

- `scripts/librarian-update-macos.sh`
- `scripts/librarian-update-windows.ps1`

4. CI/CD Pipeline (GitHub Actions)

- Publish GitHub releases/tags used by update checks.

## API Contract

### GET `/api/update/check`

Returns current and latest release info.

```json
{
  "ok": true,
  "repo": "reprahkcin/ollama-librarian",
  "current_version": "v1.5.0",
  "latest_version": "v1.6.0",
  "update_available": true,
  "source": "release",
  "apply_mode": "git",
  "branch": "main",
  "apply_target": "main",
  "local_sha": null,
  "remote_sha": null,
  "release": {
    "tag": "v1.6.0",
    "published_at": "2026-05-11T22:10:00Z",
    "notes_url": "https://github.com/reprahkcin/ollama-librarian/releases/tag/v1.6.0"
  }
}
```

### POST `/api/update/apply`

Starts update process asynchronously.

Request:

```json
{
  "target_version": "main"
}
```

Response:

```json
{
  "ok": true,
  "started": true,
  "job_id": "update-1778537520-a1b2c3d4"
}
```

### GET `/api/update/status`

Returns current update status.

```json
{
  "ok": true,
  "repo": "reprahkcin/ollama-librarian",
  "job_id": "update-1778537520-a1b2c3d4",
  "state": "applying",
  "step": "git_fetch",
  "progress_pct": 30,
  "message": "Fetching repository updates",
  "started_at": 1778537520,
  "finished_at": null,
  "target_version": "main",
  "last_error": null,
  "source": "git",
  "apply_mode": "git",
  "branch": "main",
  "apply_target": "main"
}
```

States:

- `idle`
- `checking`
- `available`
- `applying`
- `done`
- `failed`

## Updater Behavior

### Common Flow

1. Resolve update mode (`git` or `script`) and target.
2. Run preflight checks (branch, clean worktree, remote accessibility).
3. Start async update worker.
4. Fetch from remote and apply fast-forward sync.
5. Report `done` if changed or `Already up to date` if unchanged.
6. Report `failed` with `last_error` if any step fails.

### Required Safeguards

- One updater at a time (in-process lock/state gate).
- Timeouts per step.
- Always write structured logs for each step.

## Security Requirements

- Fetch updates only from trusted repository owner/name.
- Restrict git apply mode to the configured branch target.
- Keep update endpoints behind existing same-origin and API auth controls.

## CI/CD Release Requirements

- Trigger on tag matching `v*`.
- Publish release with:
  - release notes

## Observability

- Log file for updater operations per platform.
- Backend endpoint returns last N update events.
- UI shows concise error and suggests retry/rollback state.

## Operational Constraints

- UI update operation should be user-initiated.
- Update process must be detached from request lifecycle.
- Server response should return immediately after job launch.

## Acceptance Criteria (Feature Complete)

- User can detect newer release from app UI.
- User can trigger update with one click.
- Update applies via git/script mode and reports completion state.
- Clear status and errors visible in UI.
- Logs provide enough detail for support diagnosis.

## Open Decisions

- Whether to allow optional prerelease channel.
- Whether to support deferred reminders per version.
- Whether to include signed artifacts in v1 or later.

## Implementation Notes

- Keep update code path isolated and testable.
- Avoid coupling updater with chat/generation code paths.
- Prefer explicit status transitions over inferred state.
