# Issue: `eclipse-sync.service` is named in the US-403 allow-list but is not a deployed systemd unit

**Filed by:** Ralph (Rex) — during US-403 (System Setup menu + gated service control), Sprint 49 / V0.29.3
**Date:** 2026-06-30
**Severity:** Low (forward-compatible; honest-instrument handles it) — deploy gap, not a build blocker

## Problem

The US-403 System Setup menu, the design spec (§4.6), Iris's menu delta, and
Atlas's A-7 ruling all name **`eclipse-sync.service`** as a controllable service
(Restart / Stop). I built the install-fixed allow-list (UI mirror in
`carousel.js`, the SSOT in `src/pi/splash/service_control.py`, and the polkit
rule `deploy/polkit-rules/51-eclipse-service-control.rules`) to include it as
designed.

**But no `eclipse-sync.service` unit ships in `deploy/`.** The deployed
`eclipse-*` units are `eclipse-obd`, `eclipse-powerwatch`, `eclipse-states-http`,
`eclipse-boot-state`, and `eclipse-dashboard` (installed by the US-399 kit). Pi→
server sync currently runs **inside the orchestrator / via `sync_now.py`**, not
as a standalone unit.

## Impact

None to the US-403 mechanism — it is complete and forward-compatible:
- The allow-list + polkit rule name `eclipse-sync.service` as designed.
- Until the unit exists, a Restart/Stop on it returns an **honest `systemctl`
  failure** surfaced in the menu status line (the action path reports the real
  non-zero exit; no fabricated success — honest-instrument).

So the menu does not lie; it just can't yet act on a sync unit that isn't there.

## Recommended action (PM)

Decide one of:
1. **Add an `eclipse-sync.service`** unit (split sync out of the orchestrator) —
   the allow-list + polkit rule already accommodate it (zero US-403 changes
   needed once the unit lands).
2. **Drop `eclipse-sync` from the allow-list** if sync stays orchestrator-internal
   (then the menu shows only `eclipse-obd` + `eclipse-powerwatch`). This would be
   a one-line edit in three mirrored places (`service_control.py`, `carousel.js`,
   the polkit rule) + the menu node test.

I built to the **design as signed off** (option 1's shape). Routing to PM for the
call since it's a deploy/architecture decision, not a dev one. Documented in
`specs/architecture.md` (F-092 → "System Setup menu" → Deploy note).
