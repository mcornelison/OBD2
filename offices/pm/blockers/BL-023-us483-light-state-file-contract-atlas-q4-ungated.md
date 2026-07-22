# BL-023: US-483 blocked -- `light` lux state-file contract not blessed (Atlas Q-4 pending)

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Active                    |
| Blocking     | US-483 (light-feed brightness consumer, Sprint 61 / V0.29.15) |
| Waiting On   | Atlas Q-4 ruling: the `light` lux state-file contract (state-file seam shape + freshness field + fallback-when-absent semantics) |
| Created      | 2026-07-22                |

## Description

US-483 is the highest-priority unclaimed story in Sprint 61. Its own
`conditionalOutcomes` gate it:

> GATED on Atlas Q-4: the `light` lux state-file contract (state-file seam +
> fallback-when-absent). **Do NOT finalize the contract shape before Atlas
> blesses it.** The near-term fixed-fallback slice is buildable now; the
> live-lux consumption lands with the EDR reader (W-9).

Three acceptance criteria cannot be met without that contract, and meeting them
requires finalizing the very shape the gate forbids finalizing:

- **AC1** -- "display reads `light.lux` (+ freshness) from the `light` state file;
  brightness = clamp(MIN, curve(lux), 1.0)". Reading `light.lux` + a freshness
  field defines the consumer-side contract shape.
- **AC5** -- "consumes the state file only". Same contract dependency.
- **VC2** -- "inject a fresh `light.lux` state file -> brightness tracks the curve".
  Not testable without a defined file shape.

Ground truth checked before filing:
- No Atlas Q-4 ruling in `offices/ralph/inbox/` (newest inbox item 2026-07-04,
  predates this sprint). DELTA-2 (display is a *pure consumer*) is cited as
  already ruled; **Q-4 (the contract shape itself) is not.**
- No `light` state-file **consumer** contract exists in the codebase. The only
  `light` references (`src/pi/sensors/sensor_reader.py`, `src/pi/bus/sample.py`,
  `src/pi/bus/edr_persistence_subscriber.py`) are the EDR sensor **producer**
  side (W-9), not a dashboard `states/` file the display reads. The states/ dir
  contract shipped in US-480-a covers system-status / battery-health / dtc only.

This is a safety-adjacent surface (screen brightness + a legible-floor guard
that must never dim a live STOP alarm below readability), so guessing the seam
shape and reworking later is the wrong risk to take. Refusal Rule 1 (Refuse
First) + Refusal Rule 2 (Ground Every Number) apply.

## Impact

- **1 story stalled** (US-483, size M). The sprint is NOT fully blocked:
  US-484 (green + text-primary reconciliations -- the non-Spool-gated parts),
  US-485, US-486, US-487 remain buildable. Ralph continues the loop on the next
  available story; no `SPRINT_BLOCKED`.
- The ALARM FLOOR (AC2) and the honest fixed-default fallback (AC3) are
  *independent of lux* and buildable now, but on their own they cannot make the
  story pass (AC1/AC5/VC2 remain unmet), so they are held pending the resolution
  choice below rather than shipped as a half-story against a shape that may change.

## Attempted Solutions

- Searched `offices/ralph/inbox/` for any Atlas Q-4 / `light` state-file / lux /
  DELTA-2 ruling: none present for this sprint.
- Searched `src/` for an existing `light` state-file consumer contract to mirror:
  none -- only the EDR producer side exists.

## Proposed Resolution

PM (Marcus) / Atlas to pick one:

- **(A) Atlas blesses the Q-4 `light` state-file contract** -- define the seam:
  file location (`/run/eclipse-obd/states/light` presumably, mirroring US-480-a),
  fields (`lux` + a timestamp/freshness marker), and the absent/stale fallback
  semantics. Ralph then builds the full consumer (live-lux curve + alarm floor +
  honest fallback) against the blessed shape. **Preferred** -- delivers the whole
  story.

- **(B) Descope US-483 for this sprint to the ungated slice** -- ship only the
  honest fixed-default brightness + the lux-independent ALARM FLOOR guard + the
  "no fake 'auto' when there is no live feed" honest-instrument behavior (AC2 +
  AC3), with the live-lux read + curve (AC1/AC5/VC2) explicitly deferred to the
  W-9 EDR reader story. Requires PM to rewrite the ACs so the reduced scope can
  reach `passes: true` this sprint.

Either path unblocks. Until one is chosen, US-483 stays `status: blocked` in
`sprint.json` so the loop advances to the next available story.

## Resolution

[Fill in when resolved]
