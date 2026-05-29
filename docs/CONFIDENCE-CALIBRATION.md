# Confidence Calibration (Phase 5)

This document describes the confidence-band policy used for citation badges.

## Goal

- Keep confidence labels interpretable.
- Avoid persistent all-High or all-Low collapse.
- Keep tooltip data aligned with label decisions.

## Inputs

For each citation, the policy uses:

- retrieval score (`score`)
- score rank among citations in the same answer
- score range (`max_score - min_score`)

## Label Policy

1. Unknown

- If citation score is missing or invalid.

2. Tight-range rank policy

- Triggered when score spread is small (`<= 0.18`) and there are at least 3 scored citations.
- Labels are assigned by rank buckets:
  - top ~30%: High
  - next ~40%: Medium
  - remainder: Low
- This prevents collapse when scores cluster tightly.

3. Relative-score policy

- Used when score spread is not tight.
- Relative score = `score / max_score`.
- Thresholds:
  - `>= 0.86`: High
  - `>= 0.62 and < 0.86`: Medium
  - `< 0.62`: Low

## Output Fields

Each structured citation may include:

- `confidence_label`: `High` | `Medium` | `Low` | `Unknown`
- `confidence_class`: `conf-high` | `conf-medium` | `conf-low` | `conf-unknown`
- `confidence_title`: tooltip text with score/rank/range rationale

## Frontend Behavior

- If structured confidence fields are present, UI badges use them directly.
- If absent, UI falls back to legacy score-based local calculation for compatibility.

## Snapshot Coverage

Route tests assert:

- Structured citations include confidence fields.
- A representative 3-score set yields all three labels (`High`, `Medium`, `Low`).
- Existing structured confidence fields are preserved.
