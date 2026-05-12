# Update Flow Recovery Runbook

Use this runbook if implementation or rollout goes sideways and you need a clean, repeatable restart.

## Goals

- Preserve useful work.
- Restore a known-good baseline.
- Rebuild implementation with minimal ambiguity.
- Re-validate safety and rollback before release.

## 1) Triage and Stabilize

- Stop active feature rollout.
- Do not ship additional update-flow changes until triage is complete.
- Capture current branch name and commit hash.

Commands:

```bash
git branch --show-current
git rev-parse --short HEAD
git status --short
```

## 2) Snapshot Current State

Create an audit snapshot before any reset work.

- Save logs from app and updater scripts.
- Save a patch of current update-flow changes.
- Save CI workflow run links and failure logs.

Commands:

```bash
git --no-pager diff > /tmp/update-flow-snapshot.diff
git --no-pager log --oneline -n 50 > /tmp/update-flow-log.txt
```

## 3) Decide Recovery Strategy

Choose one path:

### Path A: Soft Recovery (preferred)

Use when implementation is mostly correct but unstable.

- Keep branch.
- Revert only high-risk commits.
- Continue using the checklist from the overview docs.

### Path B: Hard Recovery (full restart)

Use when branch is chaotic or confidence is low.

- Archive branch for forensic reference.
- Start fresh branch from clean `main`.
- Re-implement strictly by phased checklist.

## 4) Hard Recovery Procedure

### 4.1 Archive Failed Branch

```bash
git checkout <problem-branch>
git branch backup/update-flow-failed-<YYYYMMDD>
git push origin backup/update-flow-failed-<YYYYMMDD>
```

### 4.2 Create Fresh Branch

```bash
git checkout main
git pull --ff-only
git checkout -b cicd-update-flow-restart
```

### 4.3 Rehydrate Context from Docs

Start from these files only:

- docs/UPDATE-FLOW-OVERVIEW.md
- docs/UPDATE-FLOW-CHECKLIST.md
- docs/UPDATE-FLOW-RECOVERY-RUNBOOK.md

Do not rely on memory or chat history for implementation decisions.

## 5) Minimal Rebuild Order

Follow this exact order:

1. Version source and API contracts.
2. `check` endpoint.
3. `status` endpoint skeleton.
4. `apply` endpoint launcher.
5. macOS updater script.
6. Windows updater script.
7. Frontend status and buttons.
8. CI release workflow.
9. Security checks and preflight failure drills.

This order limits blast radius and keeps each milestone testable.

## 6) Validation Gates (must pass before next phase)

### Gate 1: API Contract Validity

- Endpoints return stable JSON fields.
- Error responses are deterministic.

### Gate 2: Safe Apply Flow

- Update job lock prevents overlap.
- Preflight failures abort without repo mutation.

### Gate 3: Failure Integrity

- Simulated dirty-worktree and branch mismatch fail preflight.
- App remains available and reports actionable failure states.

### Gate 4: CI Release Integrity

- Tag creates artifacts and checksums.
- Fresh machine can update from release assets.

## 7) Failure Patterns and Fixes

### Symptom: Update starts but UI hangs

Likely causes:

- No status polling updates.
- Updater process not detached correctly.

Fix:

- Ensure `apply` returns immediately with `job_id`.
- Ensure status state is persisted and updated by updater output parser.

### Symptom: Update preflight fails unexpectedly

Likely causes:

- Current branch does not match configured update branch.
- Local worktree is dirty.
- `origin` remote/branch is unavailable.

Fix:

- Checkout configured branch and retry.
- Commit/stash local changes, then retry.
- Validate `origin` remote and network access.

## 8) Go/No-Go Checklist for Relaunch

- [ ] All required checklist items complete.
- [ ] At least one full dry run on macOS.
- [ ] At least one full dry run on Windows.
- [ ] Preflight failure drills tested and successful on both.
- [ ] Researcher-facing docs updated.
- [ ] Maintainer release docs updated.

## 9) Incident Postmortem Template

Use this after any major update-flow incident:

```text
Incident Date:
Impact:
Root Cause:
Contributing Factors:
Detection Gap:
What Worked:
What Failed:
Action Items:
Owner + Due Date:
Verification Evidence:
```

## 10) Operational Recommendation

During initial rollout, enable update checks by default but keep update apply manual. This reduces user disruption while confidence builds.
