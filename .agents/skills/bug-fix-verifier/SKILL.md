# Bug Fix Verifier

Use this skill whenever investigating and fixing a bug. It enforces a strict
investigate → reproduce → fix → test → verify loop. Never skip steps.

---

## Workflow

### 1. Investigate
- Read the relevant log, error, or symptom carefully.
- Identify the **root cause** in the code — not just the symptom.
- State the root cause in one sentence before touching any code.
- If multiple bugs are found, rank by impact on the user. Fix highest-impact first.

### 2. Reproduce
- Before writing any fix, write a **failing test** (unit or integration) that
  captures the broken behavior. This test MUST fail before the fix and pass after.
- If the bug is in infrastructure or I/O that can't be unit-tested directly, at
  minimum write a test that proves the guard/invariant the fix establishes.
- Commit the failing test first (as a mental checkpoint) or keep it alongside the fix.

### 3. Fix
- Implement the **smallest root-cause fix**. Do not refactor unrelated code.
- Every change must be traceable to a specific bug in step 1.
- If the fix touches a shared code path, check all callers for regressions.

### 4. Test
- Run the full relevant test suite (not just the new test).
- All existing tests must pass. New test must pass.
- If tests are slow, run targeted tests first, then the full suite.

### 5. Verify
- After tests pass, do a final code read of the fix:
  - Does it handle all edge cases (e.g. concurrent callers, missing data)?
  - Is the fix idempotent if the same path fires twice?
  - Are there any other callers of the changed function that now see new behavior?
- Screenshot or log the result if the fix is user-visible.

---

## Rules
- Never mark a fix done until step 5 is complete.
- If a test can't be written (external I/O, Twilio, etc.), explain why and add a
  log line instead that makes the invariant observable in production.
- For fixes to race conditions, always document the timing window the fix closes.
