# BL-034 — US-560: the panel does not advertise 480x320. The pin cannot be applied.

- **Filed**: 2026-08-21 by Rex (Ralph, Agent 1), Sprint 75 / V0.29.30
- **Story**: US-560 "APPLY the US-552 mode pin on the live Pi + verify native 480x320"
- **Status**: US-560 `passes: false`. Needs an Atlas ruling (CIO ratify).
- **Blocks**: US-560 only. **Does NOT block the sprint** — US-561 is explicitly
  resolution-independent, and US-563/564/565/566 are unrelated.
- **Routed here by the code itself**: `deploy/set-display-mode.sh` interlock 5 prints
  *"if 480x320 is genuinely correct for this panel, that is an EDID finding for Atlas
  (US-552) — not something to force here."* This is that finding.

---

## 1. What happened

US-560 asked me to apply the US-552 mode pin to the live Pi and verify `fb0` reads
`480,320`. The Pi is reachable, the story's premise re-confirmed, and the pin was
attempted. **It refused, correctly, and wrote nothing.**

The panel does not advertise a 480x320 timing. There is no mode to pin.

## 2. Evidence (all measured 2026-08-21 on `chi-eclipse-01`, nothing inferred)

**The story's premise re-confirmed:**
```
cat /sys/class/graphics/fb0/virtual_size  ->  1280,720
```

**Connector discovery — exactly one connected, so interlock 2 is satisfied:**
```
card1-HDMI-A-1  connected
card1-HDMI-A-2  disconnected
```
AC-3 ("pin the connector that actually reports `connected` AT THE TIME — never an
assumed one") is **discharged**: HDMI-A-1 was discovered from sysfs by the script,
not hardcoded, and it is genuinely the connected one.

**The panel is the right panel — this is not a bench monitor:**
```
EDID mfg = OSY        (OSOYOO)
EDID name = HDMI35    (the 3.5" HDMI panel)
preferred detailed timing = 1280x720
```

**The full advertised mode list — no 480x320 anywhere:**
```
1280x720 1920x1080 1280x1024 1440x900 1280x800 1024x768 x3
800x600 x4 720x480 640x480 x3 720x400 x2
```

**The live refusal:**
```
Observed output mode: 1280x720 (from /sys/class/graphics/fb0/virtual_size).
Connected panel: HDMI-A-1
WARN: HDMI-A-1 does not advertise 480x320 in its EDID mode list.
WARN: the output mode was NOT pinned. Forcing a timing the panel never
WARN: claimed can scan out black, and this Pi has no local recovery.
EXITCODE=0
```

## 3. This is not a script bug

`tests/deploy/test_set_display_mode.py` — **9 passed, 0 failed**. The script did
exactly what it was built to do. The defect is in the *premise*, not the code.

**Root cause of the false premise — a fabricated test fixture.** US-552's bash
catalog carried:

```
# The panel's advertised mode list as a 3.5" 480x320 HDMI panel reports it:
PANEL_MODES='1920x1080 1280x720 640x480 480x320'
```

Nobody had read the panel's EDID. The fixture *asserted* a hardware fact, so the
suite could only ever go green and US-552 shipped looking applicable. This is the
same fabrication shape as the latched magnetometer and IAT-as-ambient — a value
standing in for a measurement nobody took. **Fixed in this story** (see §6).

**Secondary root cause — a unit conflation.** `docs/hardware-reference.md` records
`Resolution | 480 x 320 pixels`, and `test_setDisplayMode_defaultTarget...` grounds
the script's default against that row. But that row is the **glass**, and the script
uses it as a **KMS signal timing**. Two different quantities. The OSOYOO HDMI35 is a
**scaler panel**: 480x320 glass behind a chip that accepts standard HDMI timings and
downsamples in hardware. Pinning "the panel's native resolution" was never available.

## 4. The consequence for F-127 — this is the part that matters

The Pi is not "failing to reach native". There is **no native mode to reach**. The
panel has been hardware-downscaling all along, and the F-127 type scale is paying
for it.

A 34px "driver-must-read" value, on the 320px-tall glass:

| Signal | Aspect | Scale to glass | 34px lands at |
|---|---|---|---|
| **1280x720 (today)** | 16:9 | 0.444 stretched / 0.375 letterboxed | **~13–15 px** |
| 720x480 | **3:2 — exact match** | 0.667 uniform | **~23 px** |
| 480x320 (unreachable) | 3:2 | 1.0 | 34 px |

> Caveat, stated rather than hidden: I measured the *signal*, not the glass. Whether
> the panel letterboxes 16:9 or stretches it is not something I can see over SSH, so
> both are given. Either way today's number is roughly **half** the F-127 floor.

**US-560's AC-5 was right to be suspicious.** The 44/34/26/20/15 scale was set
against an unverified downsample, and it is currently landing at well under half its
intended physical size. That is a real, quantified legibility finding, and it is a
better explanation of the marginal arm's-length reads than anything in F-132.

## 5. A second finding, and it affects THIS sprint's chrome stories

`systemctl show eclipse-dashboard.service` — the Chromium kiosk runs with:

```
--kiosk --touch-events=enabled --noerrdialogs --disable-infobars --hide-scrollbars
--autoplay-policy=... --check-for-update-interval=... --password-store=basic
--user-data-dir=/tmp/dashboard-chromium
```

**No `--window-size`. No `--force-device-scale-factor`.** So the kiosk fills the X
screen and the dashboard renders into a **1280x720 CSS-pixel viewport**.

But US-557's band budget is ~320-canvas arithmetic ("body 224px; 3 rows + footer =
222"). **The layout is budgeted against one canvas and rendered on another.**

This is exactly the "value-changed-here / measurement-left-behind" shape that
US-555's own `conditionalOutcome` warns about — and if the chrome stories
(US-555/556/557) are built and IN-CAR-validated at 1280x720, settling the mode
question afterwards silently invalidates all three.

> I am flagging this, not ruling on it — I did not measure the rendered viewport in
> the browser, only the absence of any flag that would override it. **PM/Atlas should
> settle this before US-555/556/557 run**, not after.

## 6. What I changed (test-only, disposition-independent)

Nothing in `deploy/`, nothing in `src/`. The target mode is Atlas's call and I did
not pre-empt it.

- `tests/deploy/test_set_display_mode.sh`
  - The fabricated `PANEL_MODES` comment now says plainly that it is a **synthetic**
    panel exercising the write path, **not** what the shipping panel reports.
  - Added `OSOYOO_HDMI35_MEASURED_MODES` — the real list, with the command and date
    it was measured.
  - **Scenario 15**: the real panel → the script refuses, the boot cmdline is
    untouched, and the message routes to Atlas. 6 assertions; catalog 50 → 56.
- `tests/deploy/test_set_display_mode.py` — docstring 14 → 15 scenarios, mod history.

Scenario 15 encodes **only** what the panel offers and that we do not force a timing
it never claimed. It deliberately encodes **no** ruling on what to pin instead, so it
stays valid whichever way §7 goes.

## 7. The ruling needed (Atlas, CIO ratify)

**Do NOT let anyone "fix" this by forcing the mode.** `video=HDMI-A-1:480x320D`
would bypass EDID validation. On a panel that never claimed the timing that can scan
out black, in a car, with no local recovery. Interlock 3 exists for this. Three
fabrications in one week came from exactly this move — guessing a plausible value in
a subsystem nobody had measured.

| Option | Effect | Notes |
|---|---|---|
| **A. Pin 720x480** *(my recommendation)* | 34px → ~23px on glass, **~1.5–1.8× better than today**, zero aspect distortion | The **only** advertised mode matching the glass's 3:2. Needs **no code change** and **no forcing** — `ECLIPSE_DISPLAY_MODE=720x480 sudo bash deploy/set-display-mode.sh`. Interlock 3 passes on its own terms. |
| B. Accept 1280x720 | Status quo | Then F-127's px floors are ~half-size on glass and the scale must be **re-derived against the real scale factor**, not left as-is. |
| C. Force 480x320 | 1:1 if it works | **Black-panel risk in a car.** Would need a bench rig and a rollback path first. Not something to try remotely. |
| D. Re-source the panel | 1:1 natively | Only if a true 480x320-EDID panel exists. CIO hardware call. |

Option A is grounded entirely in the measured list — it invents nothing. It is also
the cheapest thing that moves legibility, which is F-127's whole point.

**Whatever is chosen, it changes the canvas the F-132 chrome stories are measured
against.** That ordering decision is PM's.

## 8. Knock-on

- **F-127's in-car legibility gate stays OPEN.** US-560 was supposed to discharge it
  "once the read is taken at native res". There is no native res, so the read cannot
  be taken as specified. The gate needs re-specifying against whatever §7 rules.
- **The freeze's "last untested lever" is not available as written.** Atlas ordered
  US-560 first because every freeze observation to date is at 720p/1080p and the
  shipping config had never been tested. It turns out **720p IS the shipping
  configuration** — the panel asks for it. So the freeze observations were never at
  the wrong resolution, and the mode pin is not the lever it was believed to be.
  Re-measuring the freeze after US-560 (F-133) needs re-thinking on that basis.
- `US-552` is marked `passes: true` in the Sprint 74 archive. Its *code* is sound and
  its interlocks did their job. Its *acceptance* rested on a fixture that asserted
  hardware nobody had read. PM's call whether that warrants a note on the record.
