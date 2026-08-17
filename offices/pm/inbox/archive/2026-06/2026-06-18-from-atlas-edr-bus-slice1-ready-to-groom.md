# EDR bus — Slice 1 spec + plan complete, ready to groom into a sprint

**Date**: 2026-06-18
**From**: Atlas (Architect)
**To**: Marcus (PM)
**Priority**: Normal (no deploy pressure; build-ready)

CIO directed me to design + plan gate #1 of the EDR epic (the dedicated-reader → internal bus →
subscribers pipeline; Watch List A-14). Spec and a full TDD implementation plan are written,
CIO-reviewed, and committed on `dev`. **Routing to you to groom into a sprint for Ralph**, with
Argus on validation.

## Artifacts
- **Spec:** `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- **Plan:** `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md` (9 TDD tasks, complete code)

## What slice 1 is
New `src/pi/bus/` package (`Sample`, `QoS`, `SampleBus` with STREAM+STATE + integrity-gap markers,
`Subscription` with QoS overflow) + a `PersistenceSubscriber` that writes `realtime_data` by
**reusing the existing `ObdDataLogger.logReading()`** + a publish seam in `RealtimeDataLogger`,
wired behind a `pi.bus.enabled` flag.

## Why it's low-risk to schedule now
- **Ships dark:** flag defaults `false` → merging changes nothing until someone flips it.
- **Byte-identical gate:** a golden-master test proves the bus path writes identical `realtime_data`
  rows vs today's inline path; the full fast suite must stay green with the flag off.
- **Hardware-independent:** stdlib only, no new deps, uses the existing OBD path — does **not** wait
  on the sensors (arriving ~late July) or the ECMLink spike. Buildable immediately.
- **Strangler-fig:** display, drive detector, and the sync transport are untouched (later slices).

## Sizing + dispatch notes
- ~1 sprint (9 bite-sized TDD tasks). Suggest it as the next-sprint candidate or alongside the
  US-367 ECU-backfill spine — they don't overlap.
- **Verify-before-impl flags** the plan calls out for Ralph (each at its task): exact
  `ObdDataLogger.__init__` signature, `createRealtimeLoggerFromConfig` signature, the orchestrator
  class/attribute names in `lifecycle.py`, and whether `utcIsoNow`/`getCurrentDriveId` are already
  imported in `realtime.py`.
- **Argus validation:** golden-master byte-identical rows + flag-off full-suite green.
- **Post-merge (separate gate, your/CIO call):** flipping `pi.bus.enabled=true` on the Pi and
  confirming byte-identical `realtime_data` + healthy sync — same verify-on-deploy rigor as the
  chi-srv-01 fix earlier today.

Routed a courtesy plan-pointer to Ralph's inbox (marked "await PM dispatch"). A-14 updated.

— Atlas
