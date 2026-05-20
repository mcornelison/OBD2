---
name: PM verifies diagnostic premises (not just table names) before grooming
description: Companion to feedback_pm_verify_table_names_against_code.md -- when Spool/Rex/anyone files a bug report citing a hypothesized root cause, PM verifies the HYPOTHESIS itself empirically before writing it into a story spec. Bug-reporter intent is correct; bug-reporter root cause is often partially or fully wrong.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
When a domain expert files a bug report with a hypothesized root cause, the **bug existence is usually correct** but the **hypothesized root cause is often partially or fully wrong**. PM must reproduce the symptom + verify the diagnostic chain BEFORE writing it into a sprint contract.

**Why**: Three diagnostic-premise errors in 24 hours (2026-05-08 to 2026-05-09):

1. **BL-010 (Sprint 26)**: Mike's "sync log" conversational shorthand assumed = literal `sync_log` table. Actual server table = `sync_history`. PM groomed wrong table; Rex caught at pre-flight.
2. **BL-011 (Sprint 28 mid-execution)**: Rex's 2026-05-08 inbox note hypothesized v0007 migration didn't apply on Pi. Actual: v0007 was a server-side DELETE pruner that NEVER targeted Pi (BL-010 closure had established this). PM inherited Rex's wrong premise; Rex caught his own mistake at next pre-flight.
3. **I-018 (calibration.py)**: Spool 2026-05-09 inbox Item 1 hypothesized calibration crash = missing `baselines` table. Actual reproduction: stdlib `types.py` shadow blocks import before any DB access. The missing-table issue would surface ONLY after the import bug is fixed -- two stacked failure layers, expert diagnosed only the second one.

**Pattern**: in all three cases, the diagnostic shorthand was authored quickly + felt authoritative + propagated into PM artifacts without empirical reproduction. The fix is empirical reproduction at PM grooming time.

**Rule (apply at every bug-report grooming)**:

1. **Reproduce the symptom** before writing it into a story spec. For runtime bugs: run the failing command + capture the actual error. For DB issues: run the actual query + see the actual result.
2. **Verify the hypothesized root cause is the FIRST cause**, not just A cause. Stacked failure layers are common -- expert often diagnosed layer 2 or 3 without seeing layer 1.
3. **If reproduction shows a different root cause** than the bug-reporter named, USE THE OBSERVED CAUSE in the story spec. Cite the bug-reporter's hypothesis as a known follow-up if it's still in the failure chain.
4. **If reproduction is impossible** (no production access, transient bug, environment-dependent): file as a clarifying question; mark the story `pending-investigation` rather than committing to a fix path.

**Cheap pre-flight reproduction commands** (under 60 sec each):
- Runtime crash: `python <command from bug report> 2>&1 | tail -30` -- read the trace
- DB state: `sqlite3 data/obd.db "SELECT ..."` or `mysql -e "SHOW TABLES"`
- File-existence claim: `ls <path>` or `git log --oneline -- <path>`
- Migration claim: `grep -n "class.*Migration\|def apply" src/server/migrations/versions/v0007*.py`

**Anti-patterns this rule prevents**:
- BL-010 class: PM grooms toward wrong table/file based on conversational shorthand
- BL-011 class: PM inherits a stale or wrong diagnosis from a recent inbox note
- I-018 class: PM grooms toward layer-2 cause when layer-1 cause is the actual blocker; layer-2 fix is dead code until layer-1 ships

**When to skip empirical verification**:
- Bug is fully reproduced + analyzed in the inbox note WITH the actual error message + stack trace shown verbatim (not paraphrased)
- Bug is in a domain where PM has zero authority to verify (Spool's tuning judgment, Mike's hardware feel) -- the EXPERT'S diagnosis is the authority by definition
- Bug-fix sprint is already mid-flight and a new pre-flight blocks the entire sprint -- file as next-sprint candidate instead

**Cross-references**:
- `feedback_pm_verify_table_names_against_code.md` -- narrower rule about table/symbol names
- BL-010 + BL-011 + I-018 cases -- canonical examples of premise-trust failures
- US-274 lint (file-existence check) -- catches phantom paths but NOT phantom diagnoses
