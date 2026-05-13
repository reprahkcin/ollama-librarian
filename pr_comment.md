### PR Review Summary - CICD Update Flow

This PR addresses the complete implementation and hardening of the update flow, resolving all Copilot review waves.

**Review Process Details:**
- **Copilot review waves handled:** 3+ waves of iterative fixes and refinements.
- **Major categories fixed:**
  - **Concurrency/State:** Hardened apply flow and state recovery to prevent race conditions.
  - **Endpoint Semantics:** Enforced strict check/apply semantics in server endpoints.
  - **Target Validation:** Validated origin mapping and stabilized check targets.
  - **Script Hardening:** Improved error handling and cross-platform script stability.
  - **Docs Alignment:** Aligned guides and runbooks with implementation details.
- **Key Commits:**
  - `9a49690` - fix(format): correct indentation in update apply logic and HTTP response handling
  - `ce56a6a` - docs(update): align guides with branch-target and MVP flow
  - `5eca6c6` - fix(update): enforce check/apply semantics and updater preflights
  - `2d17d9d` - fix(update): validate origin mapping and stabilize check targets
- **Validation Performed:**
  - Verified syntax via `python3 -m py_compile` and `bash -n`.
  - Status clean checks and manual smoke tests for the update flow.
- **Final Outcome:** All review threads resolved.
