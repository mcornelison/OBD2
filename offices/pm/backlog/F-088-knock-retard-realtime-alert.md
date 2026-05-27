---
id: F-088
parent: E-003
status: pending
renamedFrom: B-088
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-088: GEM-3 — Knock-retard real-time alert with chime ladder

| Field        | Value         |
|--------------|---------------|
| Priority     | High (Spool Phase-2 V0.29-V0.30; if only ONE alert lives in the 3.5 inch UI, this is the one)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | M        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

**THE most-important engine-protection alert on the screen.** The brainstorm did not mention knock retard — they did not know our drive-11 characterization.

**Thresholds (anchored on drive-11 baseline):**
- NORMAL: pull <5 degrees under load
- ALERT (yellow tile + single soft chime): pull 5-10 degrees
- WARNING (orange tile + triple chime): pull 10-15 degrees
- STOP-DRIVING (red flashing tile + continuous chime until tap-to-acknowledge): pull >15 degrees

**Required PIDs:** TIMING_ADVANCE (already captured) + correlated ENGINE_LOAD (already captured). Partial coverage works today; full coverage gates on B-074 MAP PID.

**Source:** Spool gem-filter PM note (GEM-3 + CIO A6 chime-pattern spec). Spool offered to draft preliminary PRD on PM go-ahead.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
