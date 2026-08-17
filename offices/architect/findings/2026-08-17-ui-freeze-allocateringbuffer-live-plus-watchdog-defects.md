# Finding — AllocateRingBuffer UI freeze is LIVE in V0.29.29 (bench/1080p only) + 4 watchdog defects + unpinned library constraints

**Author:** Atlas (Architect)
**Date:** 2026-08-17
**Task:** CIO reported "V0.29.29 UI freezes right after 1 minute, sometimes closes and resets, not consistently."
**Target:** LIVE Pi `10.27.27.124` (`chi-eclipse-01`), V0.29.29 / `46bb187`.
**Severity:** Med-High on the freeze (**scope-limited — see §0**); Med on the watchdog; Med on library pinning.

---

## 0. SCOPE LIMIT — READ THIS BEFORE GROOMING

**The freeze was observed ONLY on the bench, at 1920×1080, on a desktop monitor.
It has NEVER been observed on the 3.5″ panel, because V0.29.29 has never run on it.**

The CIO's 3.5″ OSOYOO panel is in the car. His bench Pi is driving a **Samsung SA300/SA350**
(EDID-confirmed) at 1080p — **~13× the pixel count** of the 480×320 target, with a different KMS mode
and a different GPU rasterization load.

**Do NOT groom this as a confirmed in-car regression.** It is a confirmed BENCH regression whose
behaviour on target hardware is unknown. The gating question — *does it reproduce at 480×320?* — is
unanswered and cannot be answered on the bench (that monitor advertises only 1920×1080 and 1080i, so
there is no cheap downscale A/B).

---

## 1. The freeze IS the AllocateRingBuffer class, and US-522 did not remove it

The kiosk watchdog caught it in the act (its own words):

```
16:18:32 WARNING kiosk-watchdog: kiosk eclipse-dashboard.service WEDGED --
         101 'AllocateRingBuffer' errors within 60s; restarting (attempt 1 of 5 this hour).
         US-522 was supposed to remove this failure class: a restart here means it is still live.
16:18:32 WARNING kiosk-watchdog: eclipse-dashboard.service restarted; display should be live again
```

Observed cycle:

```
16:14:57  chromium starts (NRestarts=0, clean launch)
~16:15    UI paints; top-bar clock reads 4:15
          -> display freezes (clock stops, unresponsive, froze mid-swipe on one occasion)
16:18:32  marker BURST -> watchdog restarts kiosk
~16:18    UI back; clock advances 4:18 -> 4:19 -> 4:20
~16:20    frozen again, on card 3
```

**Life expectancy ≈ 1.5-2 min per kiosk generation.**

## 2. Causes ELIMINATED (each on evidence, not reasoning)

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Auto-rotate spin (the V0.29.25 root) | **NO** | `pi.display.carousel.autoRotateS: 0`; `config.local.json` overlay contains ONLY `{"pi.power.mode": "wall"}` |
| CMA exhaustion | **NO** | `CmaFree 251904 / CmaTotal 262144 kB` = **96% free while frozen** |
| Kernel V3D hang/reset (known Trixie class) | **NO** | 2 `v3d` messages total, both benign; no MMU errors, no GPU reset |
| OOM | **NO** | 3.1 GB used of 16 GB; no OOM killer entries |
| **Live IMU face 10 Hz repaint (my hypothesis)** | **NO** | The I²C bus wedged at 16:15:25, so the IMU was DEAD for the entire freeze window — the home slot was on the STATIC fallback face, not animating. **It froze anyway.** |
| Unbounded gTrail/gradeTrend growth | **NO** | Both are time-windowed (`pushGTrail` / `pushGradeTrend`) |

So the fault is **inside chromium's GPU process**, with a bare configuration: rotation off, no live
animation, memory healthy, kernel driver clean. **That the animation hypothesis died is important** —
it removes the most convenient "it's the new IMU card" explanation.

## 3. FOUR watchdog defects (real, and independent of resolution)

### 3a. Threshold miscalibrated for THIS regime — false "healthy"

```
16:18:32  WEDGED -- 101 markers  -> restart
16:19:32  no action (healthy; markers=84, restarts this hour=1)
```

`DEFAULT_ERROR_THRESHOLD = 100`, calibrated against a catastrophic wedge measured at **~30,000 markers
per 60 s window** (`kiosk_watchdog.py:96-101`). The observed regime is **84-101** — a slow trickle
sitting exactly ON the boundary, ~1/300th the calibration rate.

**`healthy; markers=84` is a false clean bill of health** — healthy was defined as measured ZERO. The
display can be frozen while the watchdog reports healthy. **This is the "not consistently" the CIO
reported.**

### 3b. `journalctl --grep` exit-1 misread as "journal unreadable"

```
WARNING kiosk-watchdog: journalctl exited 1 -- treating the journal as unreadable
INFO kiosk-watchdog: no action (journal_unreadable; markers=None, restarts this hour=0)
```

`journalctl --grep=` **exits 1 when there are zero matches**. The watchdog invokes
`journalctl -u <unit> --since=@N --grep=<marker> ...` (`kiosk_watchdog.py:325-333`) and treats any
non-zero exit as unreadable. **So a perfectly healthy kiosk is reported as an honest-unknown.**

The docstring states the intent: *"Marker count (0 == readable and clean), or None if the journal could
not be read at all -- an honest 'unknown', never a silent 0."* **It achieved the inverse: a silent
UNKNOWN when the truth is a clean zero.** It also makes a genuinely broken journal indistinguishable
from a healthy one — the instrument cannot report its own good news.

### 3c. ~3 minute detection lag

The display froze at ~16:15; the marker burst did not fire until **16:18:32**. Markers are a **lagging**
indicator — they appear when allocation is finally attempted, not when painting stops. **The watchdog is
structurally blind for the first ~3 minutes of every freeze**, so its 60 s window cannot mean "detected
within 60 s of the freeze."

### 3d. Restart budget exhausts in ~18 minutes

`DEFAULT_MAX_RESTARTS_PER_HOUR = 5` against an observed ~3.5 min wedge-to-wedge cycle → the budget is
spent in ~18 min, after which the watchdog stops restarting **by design** and the display stays frozen
until a human intervenes. Correct policy, but on this cycle it is reached fast.

## 4. Library / version consistency (CIO-requested audit)

**Every installed package SATISFIES `requirements-pi.txt`. No unmet constraint.**

| Package | Required | Installed |
|---|---|---|
| `obd` | `>=0.7.1` | 0.7.3 |
| `adafruit-blinka` | `>=8.0.0` | 9.0.4 |
| `smbus2` | `>=0.4.0` | 0.6.1 |
| `adafruit-circuitpython-tsl2591` | `>=1.3.0` | 1.4.8 |
| `adafruit-circuitpython-icm20x` | `>=1.0.0` | **2.1.10** |

**The structural defect: every constraint is `>=` with NO upper bound.** The codebase is not pinned to
anything it was tested against; a rebuild installs whatever is newest.

**Worked example already paid for:** `adafruit-circuitpython-icm20x` permits `>=1.0.0` while **2.1.10**
is installed — across a MAJOR version boundary, which is exactly where semver permits breaking changes.
**US-500** (the genuine ICM-20948 lacking `.temperature`, which crashed the reader) was treated as a
hardware quirk; it is equally a symptom of an unpinned major-version jump.

Two smaller items:
- `RPi.GPIO>=0.7.1` is still REQUIRED although its own inline comment says it is unsupported on Pi 5.
  The journal carries `PldSensor unavailable on GPIO6 ('GPIO busy')` every boot — worth checking for an
  `lgpio`/`RPi.GPIO` conflict.
- Graphics stack is very new: **Chromium 151.0.7922.137 / Mesa 26.2.0 / kernel 6.18.39+rpt-rpi-2712 /
  Debian 13**. Raspberry Pi forums show active Chromium-on-Trixie regressions in this period.

## 5. US-552 — correctly skipped, never validated

`cmdline.txt` carries **no `video=` token**; `fb0` is 1920×1080.

**This is NOT a deploy bug.** `deploy/set-display-mode.sh` writes only when EXACTLY ONE HDMI connector
reports `connected`, and otherwise WARNs and exits 0 (`:31,:157-159`) so a deploy cannot be blocked by an
unplugged panel. The step IS wired in (`deploy-pi.sh:2067`). At deploy time no panel was attached, so it
correctly did nothing. **I initially mis-called this an A-16 deploy gap; it is the script working as
designed.**

**What IS owed: US-552 has never been applied or validated on the real panel.** F-127's in-car
legibility check remains outstanding, and the mode pin is untested end-to-end.

**Connector caution for whoever does it:** the pin is connector-specific. Mapping is now CONFIRMED —
the CIO's convention is **port 1 = 3.5″ car panel, port 2 = desk monitor** (he corrected an initial
transposition), consistent with the live reading: `HDMI-A-2` connected, EDID = **Samsung SA300/SA350**
desk monitor; `HDMI-A-1` disconnected (the panel is in the car). Still **re-read
`/sys/class/drm/*/status` at pin time and pin whichever connector actually reports `connected`** —
pinning 480×320 onto a desktop monitor would blank it.

## 6. Recommended sequence (Atlas)

1. **Do not chase the freeze further on the bench.** The one un-eliminated variable is resolution, and
   the bench monitor offers no smaller mode to A/B against.
2. **Get V0.29.29 onto the 3.5″ panel**, pin the mode to the verified connector, reboot, retest. That
   simultaneously discharges the owed F-127 in-car legibility validation.
3. **If it still freezes at 480×320** → a real regression that follows to the car; escalate then, with
   the eliminations in §2 already banked.
4. **The §3 watchdog defects and §4 pinning ship regardless** — they are resolution-independent.

## 7. Honesty notes

- All live commands were read-only: `journalctl`, `systemctl show`, `ps`/`top`, `cat` of tmpfs/sysfs,
  `pip list`, and one `sqlite3 mode=ro` using `max(id)` (NOT `count(*)` — a 3.1 M-row scan on a live
  2.3 GB DB is itself contention, which I had done earlier and should not have).
- **No I²C commands were run this boot**, per the §5b-i standing rule in the companion finding.
- I called the fork wrong once: at 16:16:39 I measured 1 marker/90 s and concluded "not the known
  class." I had measured during the lag window (§3c). Corrected on the 16:18:32 burst.
- I also wrongly framed the 1080p framebuffer as a 13× over-render pathology before learning the desk
  monitor was attached. At 1080p into a 1080p monitor the render is correct; the 13× figure applies only
  as a comparison to the 480×320 TARGET, not as a defect.
- **Cross-ref:** the I²C bus wedged spontaneously at 16:15:25 under IMU load with no involvement from me
  (324 controller timeouts). That is a SEPARATE hardware/connection fault — see the companion finding
  §5b/§5b-i — and it is why the IMU was dead during the freeze window.
