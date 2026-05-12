# Update Flow Checklist

Use this checklist as the execution plan and release gate.

## 0) Branch and Tracking Setup

- [ ] Create/confirm working branch (`cicd`).
- [ ] Create project board or issue list for each phase below.
- [ ] Link this checklist and overview doc to the tracking issue.

## 1) Contract and Versioning

- [ ] Add version source file (`scripts/VERSION`).
- [ ] Define update API schemas in code comments or docs.
- [ ] Decide stable channel behavior (default only for MVP).
- [ ] Add config constants for repo owner/name and check interval.

Definition of Done:

- [ ] Current version is readable from runtime.
- [ ] API response examples match implementation structures.

## 2) Backend API Surface

- [ ] Implement `GET /api/update/check`.
- [ ] Implement `POST /api/update/apply`.
- [ ] Implement `GET /api/update/status`.
- [ ] Add in-memory + persisted update job state.
- [ ] Add job lock to prevent concurrent updates.

Definition of Done:

- [ ] Endpoints return predictable JSON with explicit states.
- [ ] Second apply request is safely rejected while one job is active.

## 3) Release Discovery

- [ ] Implement GitHub release fetch logic.
- [ ] Validate release tag format.
- [ ] Resolve platform-specific artifact URL + checksum.
- [ ] Handle network errors, rate limits, and malformed release data.

Definition of Done:

- [ ] `check` endpoint correctly reports update/no-update.
- [ ] Failure modes return actionable error messages.

## 4) macOS Updater Script

- [ ] Create `scripts/librarian-update-macos.sh`.
- [ ] Add steps: download, verify, stop, backup, apply, health check, restart.
- [ ] Add rollback on failure.
- [ ] Emit structured status/log lines consumable by backend.

Definition of Done:

- [ ] Happy path update succeeds locally.
- [ ] Forced verify failure aborts safely with no install mutation.
- [ ] Forced health-check failure rolls back successfully.

## 5) Windows Updater Script

- [ ] Create `scripts/librarian-update-windows.ps1`.
- [ ] Implement same lifecycle as macOS script.
- [ ] Include safe process stop/start and path handling.
- [ ] Include rollback and status logging.

Definition of Done:

- [ ] Happy path update succeeds on Windows environment.
- [ ] Failure scenarios preserve recoverable install state.

## 6) Frontend UX

- [ ] Show current version in UI.
- [ ] Add `Check for updates` button.
- [ ] Add `Update now` button when available.
- [ ] Add update state/progress panel.
- [ ] Add link to release notes/changelog.

Definition of Done:

- [ ] User can complete update without terminal access.
- [ ] Status transitions and failure messages are clear.

## 7) CI/CD Pipeline

- [ ] Add GitHub Actions workflow for tagged releases.
- [ ] Build/package macOS + Windows artifacts.
- [ ] Generate SHA-256 checksums.
- [ ] Publish release assets and release notes.
- [ ] Store build metadata for troubleshooting.

Definition of Done:

- [ ] Tag push produces complete release package automatically.
- [ ] Released checksums match downloaded artifacts.

## 8) Security Hardening

- [ ] Enforce HTTPS-only artifact URLs.
- [ ] Verify checksum before apply.
- [ ] Enforce repo owner/name allowlist.
- [ ] Reject downgrades by default.
- [ ] Keep API auth and same-origin checks on update routes.

Definition of Done:

- [ ] Tampered artifact is rejected.
- [ ] Untrusted source is rejected.

## 9) Test Plan

### Unit Tests

- [ ] Version parsing and comparison.
- [ ] Release metadata parsing.
- [ ] State machine transitions.

### Integration Tests

- [ ] `check` endpoint with mock release data.
- [ ] `apply` endpoint starts detached updater process.
- [ ] `status` endpoint reflects progress and terminal states.

### Manual Tests

- [ ] No update available path.
- [ ] Update available + successful apply path.
- [ ] Network failure during download.
- [ ] Checksum mismatch.
- [ ] Restart failure and rollback.

Definition of Done:

- [ ] Test evidence captured in PR description.

## 10) Documentation and Handoff

- [ ] Update README with update flow basics.
- [ ] Add researcher-facing instructions to setup docs.
- [ ] Add maintainer release steps.
- [ ] Add troubleshooting references.

Definition of Done:

- [ ] New maintainer can run release process from docs only.

## 11) Release Readiness Gate

- [ ] All checklist sections complete.
- [ ] One full end-to-end dry run completed.
- [ ] Rollback drill completed successfully.
- [ ] Final security review completed.
- [ ] Sign-off from maintainer.

## Optional Enhancements (Post-MVP)

- [ ] Prerelease channel support.
- [ ] Signed artifact verification.
- [ ] Deferrable reminders.
- [ ] Delta updates.
- [ ] Background auto-check scheduling and quiet prompts.

## Progress Log Template

Use this block in PRs/issues:

```text
Date:
Owner:
Phase:
Completed:
Blocked:
Risk:
Next Action:
Evidence (logs/tests):
```
