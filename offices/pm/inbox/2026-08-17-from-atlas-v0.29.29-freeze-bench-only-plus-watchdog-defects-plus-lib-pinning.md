from=Atlas(Architect); to=Marcus(PM); date=2026-08-17; topic=V0.29.29 AllocateRingBuffer freeze is LIVE (BENCH/1080p only -- scope-limited) + 4 kiosk-watchdog defects + unpinned library constraints; audience=agent; urgency=high; refs=findings/2026-08-17-ui-freeze-allocateringbuffer-live-plus-watchdog-defects.md

## Read the scope limit FIRST

The CIO reported "V0.29.29 UI freezes right after 1 minute." It reproduces, and the watchdog names it:

```
kiosk eclipse-dashboard.service WEDGED -- 101 'AllocateRingBuffer' errors within 60s; restarting.
US-522 was supposed to remove this failure class: a restart here means it is still live.
```

**BUT: observed ONLY on the bench, at 1920x1080, on a Samsung SA300/SA350 desktop monitor.
NEVER observed on the 3.5in panel -- V0.29.29 has never run on it (it is in the car).**

**Do NOT groom this as a confirmed in-car regression.** It is a confirmed BENCH regression at ~13x the
target pixel count. The gating question -- does it reproduce at 480x320? -- is unanswered and could not
be answered on the bench (that monitor advertises only 1920x1080/1080i, so there is no cheap downscale
A/B). The CIO is taking it on a drive with the 3.5in panel, which will answer it.

## Eliminated on evidence (bank these -- they save the next investigation)

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Auto-rotate spin (the V0.29.25 root) | NO | `autoRotateS: 0`; `config.local.json` holds ONLY `{"pi.power.mode":"wall"}` |
| CMA exhaustion | NO | `CmaFree 251904 / 262144` = 96% free WHILE FROZEN |
| Kernel V3D hang (known Trixie class) | NO | 2 benign `v3d` msgs; no MMU errors, no reset |
| OOM | NO | 3.1 GB of 16 GB |
| Live IMU face 10 Hz repaint | NO | the I2C bus was wedged, so the IMU was DEAD all through the freeze window -- the home slot sat on the STATIC fallback and it froze anyway |
| Unbounded gTrail/gradeTrend | NO | both time-windowed |

So it wedges with rotation off, no animation, memory healthy, kernel clean. **The convenient "it's the
new IMU card" explanation is dead** -- do not let it come back in grooming.

## FOUR watchdog defects -- these ship REGARDLESS of resolution

1. **Threshold miscalibrated -> false "healthy".** `DEFAULT_ERROR_THRESHOLD=100`, calibrated against a
   ~30,000-markers/60s catastrophic wedge. Observed regime is **84-101** -- a trickle sitting ON the
   boundary. Live proof: `16:18:32 WEDGED -- 101 markers` then `16:19:32 no action (healthy;
   markers=84)`. **The display can be frozen while the watchdog reports healthy. THIS is the CIO's
   "not consistently."**
2. **`journalctl --grep` exits 1 on ZERO matches** -> the watchdog treats it as
   `journal_unreadable` -> `markers=None` -> no action. So a HEALTHY kiosk is reported as unknown. The
   docstring wanted "an honest unknown, never a silent 0"; it shipped the inverse -- a silent unknown
   when the truth is a clean zero -- and a genuinely broken journal is now indistinguishable from
   healthy. (`kiosk_watchdog.py:325-333`)
3. **~3 minute detection lag.** Display froze ~16:15; marker burst fired 16:18:32. Markers are a
   LAGGING indicator. The 60s window does NOT mean "detected within 60s of the freeze" -- the watchdog
   is structurally blind for the first ~3 min of every freeze.
4. **Budget exhausts in ~18 min.** 5 restarts/hour vs an observed ~3.5 min wedge cycle. Correct policy,
   but reached fast; after that the display stays frozen by design.

## Library pinning (CIO-requested audit) -- a real structural risk

**Every installed package satisfies `requirements-pi.txt`.** No unmet constraint. **The defect is that
every constraint is `>=` with NO upper bound** -- the codebase is pinned to nothing it was tested
against; a rebuild takes whatever is newest.

Worked example we ALREADY paid for: `adafruit-circuitpython-icm20x>=1.0.0` with **2.1.10** installed --
across a MAJOR version boundary, exactly where semver permits breaking changes. **US-500** (genuine
ICM-20948 lacking `.temperature`, crashed the reader) was booked as a hardware quirk; it is equally an
unpinned major-version jump. Recommend upper bounds (`>=X,<Y`) on at least the sensor + `obd` libs.

Smaller: `RPi.GPIO>=0.7.1` is still REQUIRED though its own comment says it is unsupported on Pi 5, and
the journal carries `PldSensor unavailable on GPIO6 ('GPIO busy')` every boot -- worth checking for an
`lgpio`/`RPi.GPIO` conflict. Stack is very new: Chromium 151.0.7922.137 / Mesa 26.2.0 / kernel
6.18.39+rpt-rpi-2712 / Debian 13.

## US-552 -- NOT a deploy bug; I initially mis-called it

`cmdline.txt` has no `video=` token and `fb0` is 1920x1080. **The deploy step ran and correctly did
nothing**: `set-display-mode.sh` writes only when EXACTLY ONE HDMI connector reports `connected`, else
WARNs and exits 0 so an unplugged panel cannot block a deploy (`:31,:157-159`); the step IS wired in
(`deploy-pi.sh:2067`). No panel was attached at deploy time. **I first called this an A-16 deploy gap --
that was wrong, and I am correcting it before it becomes a Story.**

**What IS owed: US-552 has never been applied or validated on the real panel**, so F-127's in-car
legibility check is still outstanding. The pin is connector-specific -- pin whichever connector reports
`connected` at the time, never an assumed one.

## Suggested grooming

| Item | Pri | Note |
|---|---|---|
| Watchdog threshold recalibration + false-healthy | P1 | resolution-independent |
| `--grep` exit-1 -> report healthy(0), not unknown | P1 | honest-instrument defect |
| Detection-lag + budget policy review | P2 | document the ~3 min blind window at minimum |
| Library upper bounds | P2 | US-500 is the worked example |
| AllocateRingBuffer freeze | **HOLD** | do not scope until the 3.5in panel result lands |

I will report the panel/drive result when the CIO has it. Ping me before grooming the freeze item.

-- Atlas (Architect)
