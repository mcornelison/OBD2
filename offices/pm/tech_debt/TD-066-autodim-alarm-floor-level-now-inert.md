# TD-066 — `pi.display.autoDim.alarmFloorLevel` is now an inert config key

- **Filed by:** Ralph (Rex), Sprint 62 (V0.29.16), during US-484-b.
- **Severity:** low (no runtime defect; it is config-drift / false-affordance risk).
- **Type:** tech-debt / config-SSOT.

## What

US-484-b implemented Spool §6d ch.4: **a live STOP alarm is FULL brightness
always**, overriding the US-483-b auto-dim curve, the honest fallback default,
and the alarm *floor*. `carousel.js brightnessLevel()` now short-circuits:

```js
if (alarmActive) return STOP_ALARM_LEVEL;   // 1.0
```

`brightnessAlarmActive()` is true **only** for a STOP-tier hero (Iris AC-7
scope — a WATCH/MINOR is a real code but not the pull-over alarm). So the only
condition that ever consumed `alarmFloorLevel` is now the condition that returns
full. The key is live in three places but reachable from none:

- `config.json` → `pi.display.autoDim.alarmFloorLevel: 0.40`
- `src/common/config/validator.py:357` (default) + `:852` (fraction-range check)
- `carousel.js BRIGHTNESS_DEFAULTS.alarmFloorLevel` (resolved, never read)

## Why it's out of US-484-b scope

Deleting a grounded config key that Spool set is a tuning/design call, not a
build call — and leaving it *resolvable* was the safe choice this sprint: an
already-deployed `config.json` still carries the key, and `resolveAutoDimConfig`
must not choke on it. Removing it needs the deploy-side config to change in
lockstep.

There is also a real question behind it: **should a WATCH-tier alert have a
brightness floor?** Today it has none (it dims with ambient like any other
content). If Spool wants one, `alarmFloorLevel` is the key that already exists
for it — repurpose rather than delete. That is a Spool call.

## Suggested fix (future story)

1. Ask Spool: does WATCH (or any non-STOP alert) warrant a brightness floor?
2. **If yes** — repoint `alarmFloorLevel` at a `watch`-tier predicate and keep
   the STOP full-brightness override above it (a two-tier guard).
3. **If no** — remove the key from `config.json`, `validator.py` (default +
   range check), and `BRIGHTNESS_DEFAULTS`, and drop it from the `_CFG` fixtures
   in `tests/ui/test_carousel_brightness.py` /
   `tests/ui/test_dashboard_stop_tier_safety.py`. Deploy must land the
   `config.json` half in the same release.

Until then the inline comment at `carousel.js` `BRIGHTNESS_DEFAULTS` says the key
is superseded, so nobody tunes it expecting an effect.

## Grounding

- `offices/tuner/dtc-display-clear-safety-advisory.md` §6d ch.4 — "a 🔴 alarm is
  full brightness always, independent of auto-dim… only ambient content dims."
- `specs/UI/dist/dashboard-pi/carousel.js` — `STOP_ALARM_LEVEL`,
  `brightnessLevel`, `brightnessAlarmActive`, `BRIGHTNESS_DEFAULTS`.
- `src/common/config/validator.py:357,852` — the key's default + range check.
- `tests/ui/test_dashboard_stop_tier_safety.py` — the ch.4 tests that pin
  full-brightness-over-floor (the fixture deliberately sets 0.40 to prove the
  override wins).
