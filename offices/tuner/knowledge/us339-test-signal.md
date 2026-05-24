# Spool — US-339 Validation Signal is FD-Count Stability, Not Journal Grep

> Spool persona / analytical guardrail. Migrated 2026-05-18 from `~/.claude/.../feedback_us339_test_signal_is_fd_count_not_journal_grep.md` per CIO directive.

When testing the US-339 fd-leak fix (I-034 SQLite disk-I/O on long uptime), the **only meaningful test signal is fd count stability** for the eclipse-obd PID over a sustained soak.

**Why:** The bug class was an fd-leak in `pushDelta` / `pushDriveCounter` from `with sqlite3.connect()` that commits but does NOT close the connection. Accumulated leaked fds would *eventually* cause SQLite to throw its generic `disk I/O error` exception class — but that's a downstream consequence of fd-exhaustion, not a primary failure mode. CIO clarification 2026-05-14: "I dont think we ever had disk I/O errors... it is a brand new high quality disk."

The sprint.json `bigDefinitionOfDone` clause `"zero disk-I/O-error lines in journal"` is a noise check — those lines were never expected to appear even in the failure case unless the leak ran for many hours. Absence proves nothing.

**How to apply:**
- US-339 validation = **`ls /proc/<eclipse-obd-pid>/fd | wc -l` over time**. Baseline at startup, recheck at +1h, +3h, +6h.
- Fix is holding if fd count stays flat at startup-steady-state (~25 observed 2026-05-14; sprint.json said target ~5-10 but actual is higher and that's OK if STABLE).
- Fix is broken if fd count climbs steadily over hours.
- Do NOT make absence of "disk I/O error" journal lines a pass criterion by itself.

**Related pattern:** When sprint.json or PM notes frame a bug by its symptom rather than its mechanism, Spool should refine framing for tests. Ask "what is the direct test of the fix?" not "what is the downstream signal of failure?"
