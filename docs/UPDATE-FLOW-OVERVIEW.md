# Update Flow Overview

## Purpose

This document defines the full update feature for Ollama Librarian:

- Detect when a newer release is available.
- Notify researchers in the UI.
- Allow one-click update from within the app.
- Apply updates safely with integrity checks and rollback.

This is the source of truth for implementation behavior.

## Scope

### In Scope

- Versioning and release contract.
- In-app update check and status UI.
- Update apply flow for macOS and Windows.
- CI/CD release automation with checksums.
- Rollback behavior and failure handling.

### Out of Scope (Initial MVP)

- Forced updates.
- Auto-updates without user action.
- Linux updater.
- Differential/binary patch updates.

## Guiding Principles

- Safety first: never replace current install without backup.
- Predictable behavior: all update states visible to user.
- Recoverability: easy rollback and restart.
- Cross-platform parity: same UX on macOS and Windows.
- Minimal trust: verify artifact integrity before apply.

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

- Build release artifacts.
- Generate checksums.
- Publish GitHub Release and metadata.

## API Contract

### GET `/api/update/check`

Returns current and latest release info.

```json
{
  "ok": true,
  "current_version": "v1.5.0",
  "latest_version": "v1.6.0",
  "update_available": true,
  "channel": "stable",
  "release": {
    "tag": "v1.6.0",
    "published_at": "2026-05-11T22:10:00Z",
    "notes_url": "https://github.com/reprahkcin/ollama-librarian/releases/tag/v1.6.0",
    "assets": {
      "macos": {
        "url": "https://.../ollama-librarian-macos-v1.6.0.tar.gz",
        "sha256": "..."
      },
      "windows": {
        "url": "https://.../ollama-librarian-windows-v1.6.0.zip",
        "sha256": "..."
      }
    }
  }
}
```

### POST `/api/update/apply`

Starts update process asynchronously.

Request:

```json
{
  "target_version": "v1.6.0"
}
```

Response:

```json
{
  "ok": true,
  "started": true,
  "job_id": "update-20260511-221200"
}
```

### GET `/api/update/status`

Returns current update status.

```json
{
  "ok": true,
  "job_id": "update-20260511-221200",
  "state": "downloading",
  "step": "download_artifact",
  "progress_pct": 42,
  "message": "Downloading release artifact",
  "started_at": 1778537520,
  "updated_at": 1778537545,
  "target_version": "v1.6.0",
  "error": null
}
```

States:

- `idle`
- `checking`
- `available`
- `downloading`
- `verifying`
- `applying`
- `restarting`
- `done`
- `failed`
- `rolled_back`

## Updater Behavior

### Common Flow

1. Validate target version and release asset.
2. Download asset to temp path.
3. Verify checksum matches expected SHA-256.
4. Stop app process cleanly.
5. Backup current installation directory.
6. Replace installation with downloaded artifact.
7. Run minimal health check.
8. Restart app.
9. Report `done` if healthy.
10. If health check fails, restore backup and report `rolled_back`.

### Required Safeguards

- One updater at a time (lock file).
- Timeouts per step.
- Never delete backup until health check passes.
- Always write structured logs for each step.

## Security Requirements

- Fetch updates only from trusted repository owner/name.
- Require HTTPS for artifact download URLs.
- Verify SHA-256 before applying update.
- Reject version downgrade by default (optional override for admins).
- Keep update endpoints behind existing same-origin and API auth controls.

## CI/CD Release Requirements

- Trigger on tag matching `v*`.
- Build and package platform artifacts.
- Produce SHA-256 checksum file.
- Publish release with:
  - artifacts
  - checksums
  - release notes
- Optionally publish machine-readable release metadata JSON.

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
- Update applies and app restarts to new version.
- Corrupt or tampered artifact fails verification and does not apply.
- Failed post-update health check auto-rolls back.
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
