---
id: US-391
title: "dtc_freeze_frame sync: quarantine unresolvable cross-tier rows after N failures (stop silent infinite retry)"
type: issue
parent: F-076
epicId: E-002
size: S
status: sprint-ready
sourceRefs: [F-076, spool-dtc-orphan-2026-06-28-defect-2, "sync.py:564"]
created: 2026-06-28
---

# US-391 — dtc_freeze_frame sync quarantine (stop silent infinite retry)

## Context

Spool (2026-06-28) found `dtc_freeze_frame` sync failing 27× per day for 3+ weeks
on a single unresolvable cross-tier record, retrying forever with no
dead-letter/quarantine/alert — a silent infinite loop that could mask a real sync
failure in the noise. "Fail loudly, no silent re-resolve" is correct per-attempt
but wrong at the queue level. This Story adds queue-level quarantine after N
consecutive failures and surfaces the event once. US-367 (separate) self-heals the
specific current orphan by backfilling the ECU lineage; US-391 is the general
safety net.

## Goal

As the sync subsystem, I want a single unresolvable freeze-frame to stop retrying
forever (it ran 27x/day for 3+ weeks with no dead-letter/quarantine/alert — a
silent infinite loop that would mask a REAL sync failure in the noise). 'Fail
loudly, no silent re-resolve' is correct per-attempt but wrong at the queue level.
After N consecutive identical resolution failures, quarantine the record
(dead-letter table OR data_quality flag — Atlas quick-read requested) and surface
it ONCE. General safety net; US-367 self-heals the current specific orphan.

## Definition of Done

- after N consecutive identical cross-tier resolution failures on the same record, the sync loop quarantines it (dead-letter table or data_quality flag) and stops re-attempting every cycle
- the quarantine event is surfaced exactly once (log/alert), not per-cycle
- a quarantined record does NOT advance sync_log.last_synced_id and does NOT block other tables/records from syncing
- quarantine is reversible: once the resolution target exists (e.g. US-367 lands), the record can re-enter the queue and sync
- Typecheck passes; tests pass; a test proves N-failures -> quarantine -> single surfacing

## Validation Criteria

- (simulate an unresolvable cross-tier row for N+1 cycles) → (quarantined after N; surfaced once; no per-cycle re-fail)
- (make the resolution target resolvable then re-run) → (record leaves quarantine and syncs)
- (inspect sync_history during the unresolvable window) → (no unbounded identical-failure spam after quarantine)

## Conditional Outcomes

- if the dead-letter-table vs data_quality-flag choice turns architectural (schema/contract impact), route to Atlas for a ruling BEFORE coding (quick-read requested 2026-06-28)

## Notes

The dead-letter-table vs `data_quality`-flag choice has an Atlas quick-read
pending (requested 2026-06-28). General safety net — distinct from US-367, which
self-heals the specific current orphan.
