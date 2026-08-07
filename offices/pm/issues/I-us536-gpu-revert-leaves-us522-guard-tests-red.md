# I-us536-gpu-revert-leaves-us522-guard-tests-red

| | |
|---|---|
| **Found by** | Ralph (Rex), during US-532 (Sprint 71 / V0.29.26) |
| **Date** | 2026-08-07 |
| **Severity** | Medium — the sprint branch has a RED suite; blocks a clean full-suite gate at integration |
| **Owner** | PM (Marcus) — US-536 is PM-landed, outside Ralph's scope fence |
| **Status** | Open |

## Summary

US-536 (commit `3e67e5d`) reverted `--disable-gpu` from
`specs/UI/dist/dashboard-pi/dashboard.service.{x11,wayland}` per CIO
disposition-B. The **US-522 guard tests that assert the flag is PRESENT were not
retired with it**, so they now fail on the sprint branch.

`tests/deploy/test_dashboard_kit.py`:

- `test_dashboardUnits_carryGpuOverrideInExecStart_us522` (line 1595)
- `test_dashboardUnits_keyringFixCoexistsWithGpuOverride_us522` (line 1733)

Both key off `_GPU_OVERRIDE_FLAG = "--disable-gpu"` (line 1536).

```
E  AssertionError: dashboard.service.wayland: lost the US-522 GPU override
E  assert '--disable-gpu' in ['__CHROMIUM_BIN__', '--kiosk',
   '--ozone-platform=wayland', '--touch-events=enabled', ...]
```

## Why this is a real finding, not noise

The tests are doing their job — they were built to catch exactly this removal.
The removal is now the INTENDED behaviour, so the guard has inverted: what used
to protect US-522 now blocks US-536. Left as-is, the first full-suite run at
integration reports 2 failures that look like a regression in the dashboard kit
and are actually a stale contract.

## Suggested disposition (PM's call)

US-536's own AC says verification should prove **`--disable-gpu` GONE,
`--password-store=basic` PRESENT**. That is the same two facts, inverted — so the
cleanest fix is to *invert* the guards rather than delete them:

1. `test_dashboardUnits_carryGpuOverrideInExecStart_us522` → assert the flag is
   ABSENT from both variants, renamed to the US-536 story.
2. `test_dashboardUnits_keyringFixCoexistsWithGpuOverride_us522` → keep the
   `--password-store=basic` half (the keyring fix explicitly STAYS per US-536
   AC-1) and drop the GPU half.

Deleting them outright would leave nothing pinning "the GPU flag did not come
back", which is the regression US-537 cares about.

## Scope note

Not fixed inline. `tests/deploy/test_dashboard_kit.py` and the dashboard unit
files are US-536's lane, US-536 is already marked `passes: true`, and Ralph's
scope fence for US-532 covered the settings band only. Flagging per the
"report, do not silently work around" rule.

## Reproduction

```bash
pytest tests/deploy/test_dashboard_kit.py -k us522 -v
```

Unrelated to US-532, and this is checkable without reverting anything (a revert
is outside Ralph's git allow-list, so it was NOT run): the failing assertions
read `dashboard.service.x11` / `dashboard.service.wayland`, and US-532's diff
(`6a4af44`) touches only `carousel.js`, `dashboard.css`, `dashboard.html` and
`states_http_server.py` — it never opens either unit file. `git log -1 --` on
those two paths returns `3e67e5d` (US-536). The settings-band suites
(`tests/ui/test_carousel_settings_band.py`,
`tests/pi/splash/test_states_http_settings_inject.py`) are green.

The full `tests/deploy/test_dashboard_kit.py` file was also GREEN earlier in this
same iteration, in the scoped regression run that completed before `3e67e5d`
landed — so the two reds appeared with US-536, not before it.
