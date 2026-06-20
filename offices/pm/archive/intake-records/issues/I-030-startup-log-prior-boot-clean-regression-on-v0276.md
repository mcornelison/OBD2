# I-030: startup_log `prior_boot_clean` field empty on V0.27.6 post-drain-17 boot (regression)

| Field | Value |
|---|---|
| Severity | Medium (P2 -- observability layer broken) |
| Status | Open (V0.27.7 candidate -- PM finding) |
| Category | observability / writer regression |
| Found In | `src/pi/diagnostics/boot_reason.py` (US-263 schema + US-287 writer + V0.27.2 US-308 graceful detection) |
| Found By | Marcus (PM) 2026-05-12 Drive 11 validation |
| Related | V0.27.2 US-308 (graceful detection added); V0.27.6 US-322 (orphan-cleanup timer -- possibly interferes); V0.27.4/5 Drain 14+15 boots had populated `prior_boot_clean=1` |
| Created | 2026-05-12 |

## Description

Post-drain-17 boot (V0.27.6) wrote a startup_log row with **`prior_boot_clean` field EMPTY** (not 1, not 0, blank). Earlier boots had `prior_boot_clean=1`:

```
recorded_at              | prior_boot_clean | prior_last_entry_ts
2026-05-12T00:37:02Z     | (empty)          | (empty)              ← V0.27.6 boot post-Drain-17
2026-05-11T12:27:57Z     | 1                | Mon 2026-05-11 ...   ← V0.27.5 boot
2026-05-10T20:00:14Z     | 1                | Sun 2026-05-10 ...   ← V0.27.4 boot post-Drain-15
```

This is a REGRESSION from V0.27.4/5 behavior. US-308 graceful detection writer was working; now it isn't (or has a race).

## Hypotheses (Ralph pre-flight identifies)

**Hypothesis A**: V0.27.6 US-322's new `orphan-cleanup.timer` (nightly at 03:00 local) runs at boot too OR creates a race with `boot_reason.py` writer. The writer's journal-parse heuristic fails if journal data not yet flushed.

**Hypothesis B**: V0.27.6 deploy artifact -- new orphan-cleanup systemd unit changed Pi boot order; boot_reason.py runs before required services are ready.

**Hypothesis C**: V0.24.1 ladder shutdown sequence on V0.27.6 differs from V0.27.4 in a way that breaks the graceful-detection regex.

Pre-flight: capture `journalctl --boot=-1` from chi-eclipse-01 (the post-Drain-17 boot). Compare graceful-shutdown log lines vs V0.27.4 reference (Drain 15 successful detection). Find the divergence.

## Impact

- US-308 graceful detection observability signal broken on V0.27.6
- Future boots will continue to write blank `prior_boot_clean` until fixed
- Spool's drain-test-procedure Step 4 query depends on this field

## Acceptance Criteria

- [ ] Pre-flight: identify which hypothesis matches the actual cause via journalctl + boot-order + writer-trace
- [ ] Fix lands; new boot post-fix produces populated `prior_boot_clean` field
- [ ] Synthetic test feeds a V0.27.6-flavor journal slice -> writer produces `prior_boot_clean=1`; regression test for graceful detection
- [ ] (Optional) Backfill the empty row from Drain 17 boot using journalctl --boot=-1 evidence

## Source

- PM 2026-05-12 Drive 11 + Drain 17 forensic pull
- V0.27.2 US-308 ship (graceful detection added)
- Cross-reference with Spool's drain-test-procedure.md Step 4 schema-mismatch note (separate procedure-doc issue; this is the writer bug)
