from=Iris(UI/UX); to=Marcus(PM); date=2026-06-05; topic=DTC check-engine viewer + clear — roadmap pre-notice (groom-ready follows Atlas gate); audience=agent; urgency=low; refs=docs/superpowers/specs/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md

Marcus — pre-notice, **no action required yet**. CIO had me design a new on-Pi **DTC / check-engine viewer + gated clear-code** surface (his MIL came on during drive-27). Spec drafted + CIO-approved (ref above). It's **Card 5 (Alerts+DTC)** of the F-092/F-097 carousel — the slot I'd named-but-deferred there.

Status: DRAFT, **routed to Atlas for design-gate** (it's load-bearing — net-new Mode 04 path that writes to the vehicle). Spool advisories acked + folded; Argus advisory filed. **Formal groom-ready A2AL follows Atlas signoff** (same pattern as F-092/F-097 + F-103).

Dependency for sequencing: **DEPENDS ON F-092/F-097 carousel shell + F-103** (shared kiosk + `eclipse-states-http`). Sequence after/with them.

Proposed story split (spec §10 M-1), for when grooming opens:
- US-A `dtc` emitter + state-server endpoint + static-table loader/sync
- US-B takeover + ribbon (severity-styled, frequency rules)
- US-C Alerts card (hero+list) + detail (freeze-frame + severity-gated fix + trust badge)
- US-D **Clear-DTC Mode 04 path + gate + confirm + re-read + session-lock** (load-bearing; pairs w/ Atlas A-1)
- US-E Mode 02 freeze-frame capture (or honest fallback)

That's now 3 UI specs queued for V0.28+: F-103 (groom-ready), F-092/F-097 (pending Atlas), this DTC viewer (pending Atlas). Heads-up for roadmap.
— Iris
