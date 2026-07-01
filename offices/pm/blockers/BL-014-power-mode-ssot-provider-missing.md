# BL-014: US-421 power-mode SSOT provider does not exist (in-car vs wall-power)

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Active                    |
| Blocking     | US-421 (Power-mode badge -- in-car vs wall-power, F-098) |
| Waiting On   | Atlas (SSOT/architecture ruling) + CIO ratification |
| Created      | 2026-07-01                |

## Description

US-421 acceptance criterion #1 reads:

> "a small persistent badge shows current power mode, sourced from the **existing power-mode SSOT provider** (`src/pi/power/` -- confirm the provider; do NOT add a second acquisition path per the SSOT directive)"

**That provider does not exist.** Per Refusal Rule 1 (ambiguity is a blocker) I confirmed the premise before building, and it is false on both tiers of the fact:

1. **No acquisition source for the "in-car vs wall-power" fact anywhere in the codebase.**
   - `src/pi/power/power_source_provider.py` is the SSOT for a *different* fact: **external-AC vs UPS-battery** (`isExternalPowerPresent()`, wraps GPIO6 PLD). That is NOT the in-car/wall-power *deployment mode* -- both deployment modes normally read "external power present" (car = fuse-box 12V→buck; wall = AC adapter), so this provider cannot distinguish them. Using it would produce a confident wrong state, which AC #2 explicitly forbids ("undeterminable -> 'unknown', never a confident wrong state").
   - No config key exists. `config.json` + `src/common/config/validator.py` DEFAULTS have `pi.display.mode`, `pi.display.displayCanvas.mode`, `pi.calibration.mode` -- **no power mode**. (Verified by grep 2026-07-01.)
   - No env var, no runtime detector, no menu setting.

2. **The data contract for the fact already exists but is unsourced.**
   - `src/pi/splash/system_status_emitter.py::buildSystemStatusState()` already accepts a `powerMode` param documented as `` `car` (in-car) or `wall` (bench/debug)`` and writes `{"power": {"mode": powerMode, "source": powerSource}}` to the state file.
   - `specs/UI/dist/dashboard-pi/carousel.js::powerTile()` already reads `p.mode` and renders `CAR`/`WALL`/`unavailable`.
   - **But `powerMode` has no caller/source** -- `grep` finds no invocation of `makeSystemStatusEmitter(...)` in `src/`, and nothing sets `powerMode`. It is a pass-through placeholder.

`docs/pi-power-state.md` §"Two power-mode dichotomy" frames this as a **deployment-context fact** and points to **B-098** (Spool S-4) as the active-backlog item recommending "a small corner indicator: 'in-car' vs 'wall-power-debug'". It does not pin the acquisition mechanism.

## Impact

US-421 alone (size S). The dashboard/UI half is ready to render the badge the moment the source is defined; the block is purely the **acquisition SSOT design**, which is an architecture decision routed to Atlas (standing directive + PM Rule 10). Other Sprint 51 stories (US-422, US-424, US-425) are unaffected and remain pickable -- this does NOT block the sprint.

## Attempted Solutions

- Confirmed PowerSourceProvider is the wrong fact (AC/battery, not deployment mode).
- Grepped `config.json`, `validator.py` DEFAULTS, `.env.example`, `src/pi/power/*.py`, and all `makeSystemStatusEmitter` call sites -- no existing power-mode source on any layer.
- Read `docs/pi-power-state.md` (B-063 / B-098) -- confirms the fact is a deployment/config concept, mechanism unpinned.

## Proposed Resolution

Atlas to rule on the SSOT acquisition mechanism, then a small follow-up (likely still S) implements it against the already-existing `power.mode` data contract + `powerTile` renderer. Candidate mechanisms (need a ruling, do not want Ralph to guess an unratified architecture/config contract):

1. **Config key** `pi.power.mode` (enum `car` | `wall` | `unknown`, **default `unknown`**), read by a new `PowerModeProvider` in `src/pi/power/` that is THE single acquisition path (satisfies "do not add a second path" -- there are zero today). Simple; but static -- moving the Pi bench↔car needs a config edit + restart, and a wrong/stale value must resolve to `unknown` not a confident mode.
2. **Operator-settable** via the touchscreen menu (mode can change without redeploy; still backed by one provider/persisted value).
3. **Runtime detection heuristic** (e.g. GPIO/uptime/engine-signal correlation) -- most complex, most false-positive risk; likely rejected but listed for completeness.

Recommendation: **Option 1 with default `unknown`** (honest-instrument: never a confident wrong mode until the CIO sets it), optionally menu-overridable later (Option 2). Whichever Atlas rules, the badge implementation is small because the state-file field (`power.mode`) and the `powerTile` renderer already exist -- the story then adds only (a) the provider + config contract, (b) the orchestrator wiring that passes `powerMode` into the system-status emit, and (c) the persistent corner-badge DOM/CSS + fixture/DOM test.

## Resolution

[Fill in when resolved]
