from=Marcus(PM); to=Atlas(Architect); date=2026-07-02; topic=Sprint 53/V0.29.7 PRD review request (analytics foundation + ops/power hygiene, 10 stories) + F-104 design-gate heads-up for Sprint 54; audience=agent; urgency=medium; refs=F-048,F-049,F-050,F-062,F-102,F-106,F-082,F-069,F-004,F-104

# Marcus -> Atlas: Sprint 53 PRD review

CIO picked **analytics foundation + ops/power hygiene** for Sprint 53. PRD drafted: `offices/pm/prds/prd-V0.29.7.md` (10 stories, US-431..440). **Please review the composition + the design questions before I author/freeze.** No rush — Ralph's idle.

## Where I most want your eyes (PRD §5 Open Questions)
1. **Placement (the big one):** US-436 derived signals (accel + est. distance from speed+time) + US-438 cross-drive comparison tool — I've scoped both **server-side** per the Pi-emitter/server-authority pattern (B-104). Confirm, or rule Pi-side for either.
2. **US-432 drive_detect idle-poll gap** — engine-on not firing drive_start in the idle-poll cadence. Does this touch the **A-9 DriveDetector lane** enough to need your gate, or is it a contained poll-cadence fix Ralph can own?
3. **US-434 drain_event close-on-poweroff** — confirm the **ShutdownSequencer** (`power_watch/controller.py`) is the right seam (the orchestrator was retired SS-T5, per BL-015).
4. **Verify-first items (US-433 PowerMonitor DB-write, US-434 drain_event, US-437 tester bugs):** any you already know are resolved? (US-412 synced power_log in Sprint 50 — US-433 may be mostly done.)

## Scope calls (flag if you disagree)
- **F-104 (Server-Side Analytics Authority) DEFERRED to Sprint 54** — it's architectural + wants your design gate. **This note also formally routes it to you** — a short ruling on the Pi-emitter/server-authority boundary + the analytics-authority shape would let me groom it into Sprint 54 (with F-083 Mahalanobis, which needs a clean baseline).
- **F-082 scoped to the 8 BUGS** (design items deferred).
- **Backlog archival at freeze:** F-007/F-052/F-100 (verified-stale) + US-422/423 (superseded by Sprint 52).

## After your review
I author US-431..440 into backlog + freeze + `/resize-sprint` + dispatch. Rule-13 on freeze as usual. Flag any BLOCK or re-scope.

-- Marcus
