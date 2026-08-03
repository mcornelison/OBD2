# Finding — Bench UI freeze = chromium GPU command-buffer hot-loop (A-16 family)

**Date:** 2026-08-02
**Author:** Atlas (Architect)
**Severity:** High (UI unusable on the target hardware; honest-instrument violation — silent freeze, no recovery)
**Trigger:** CIO booted the V0.29.23/24 UI on the bench, used it, and it froze. OS + mouse stayed responsive; only the OBD carousel UI froze.
**Live target:** Pi `10.27.27.100` (bench, home network). All evidence captured live before mitigation.

## Symptom
Chromium kiosk display frozen (stale, never updates). OS + mouse fully responsive. No crash dialog.

## Boundary isolation (the pipeline: emitters → state files → states_http_server → chromium carousel.js)
The freeze is **entirely in chromium's GPU layer**. Everything upstream is healthy:

| Layer | Observed | Verdict |
|---|---|---|
| Emitters → `/run/eclipse-obd/states/*` | mtimes 0–3s old vs `now` (`boot-state`/`imu` 0s; `system-status`/`battery-health` 3s; `light` 1s). `imu` live: `gMag`/`headingDeg`/`pitchDeg` updating each tick | ✅ live |
| Services | `eclipse-obd`, `eclipse-boot-state`, `eclipse-states-http`, `eclipse-dashboard`, `eclipse-powerwatch` all `active/running` | ✅ up |
| System RAM | 9.9 GiB free, swap 0 used | ✅ not RAM OOM |
| chromium renderer (PID 2112) + GPU proc (2073) + main (2015) | pegged **39% / 31% / 24% CPU** for the whole 4:42 session (source of load-avg 3.35 on a 4-min-uptime Pi) | ❌ **frozen here** |
| chromium journal (`eclipse-dashboard`) | **6,063,554** `AllocateRingBuffer` fatal errors this boot; **~500/sec ongoing** (2,500 in a 5s window); **no crash / kill / OOM** logged | ❌ **GPU context dead, hot-looping** |

Exact error, repeated sub-millisecond apart:
```
ERROR:gpu/command_buffer/client/cmd_buffer_helper.cc:143]
ContextResult::kFatalFailure: CommandBufferHelper::AllocateRingBuffer() failed
```

## Root cause
Chromium's **GPU process lost/exhausted its command-buffer context**; the client then **hot-loops** on the fatal `AllocateRingBuffer()` failure (no crash, no recovery in kiosk mode) → renderer + GPU-process CPU peg → display frozen while X/OS stay live. The 6M-error, no-crash signature *is* the freeze.

**Why the GPU context died:** the Pi 5 **v3d GPU on a 64 MiB CMA pool** (`CmaTotal: 65536 kB`) is driving the freshly-deployed animated carousel (`/opt/dashboard/{carousel.js 203KB, dashboard.css 60KB}`, both deployed today 15:59) with **chromium GPU rasterization ON** (`--enable-gpu-rasterization --use-angle=gles`). The page pins permanent GPU-composited layers (`dashboard.css:204 will-change: transform` on the carousel track) plus **two always-on `infinite` CSS animations** (`dashboard.css:576 ribbon-pulse 2s ...infinite`, `:624 stop-alarm-pulse 1.1s ...infinite`). Under sustained compositing — tipped over by interaction ("after using the UI" → carousel navigation spawns more composited layers) — GPU command-buffer allocation hit a wall and the context was lost unrecoverably.

**No `backdrop-filter`** (the usual worst Pi-GPU offender) — ruled out. The `setInterval`s in carousel.js are the periodic auto-rotate, not the hot loop; the only hot loop is chromium's failed-allocation retry.

**Not deploy drift** — assets are fresh + consistent (single served docroot `/opt/dashboard` via `states_http_server --assets-dir`). This is a genuine GPU-budget defect, not stale JS.

## Confidence
- **Direct cause (GPU command-buffer hot-loop → freeze): CONFIRMED** — 6M journal errors + CPU peg + no crash.
- **Precise lever** (GPU-rasterization vs CMA size vs the specific animations): high-confidence GPU-memory/context exhaustion; *which knob eliminates it* is the testable fix-selection question below. Stated as hypothesis, not fact (avoiding an over-tidy story).

## Architectural framing — A-16 family
This is the A-16 lesson again: **merged / renders-on-desktop ≠ survives the Pi's constrained GPU.** The animated carousel passed in-repo but this is its first *sustained-use* exposure on real hardware. Bench validation caught a genuine hardware-only defect. Also an **honest-instrument** gap: the kiosk froze silently with no auto-recovery — the display should never wedge without recovering.

## Fix directions (routed; not built by Atlas)
1. **Primary — kill the failure class at the kiosk** (Ralph, `deploy/deploy-pi.sh` kiosk unit; Atlas design-gate): the dashboard is a simple 2D card UI that does **not** need GPU rasterization. Drop `--enable-gpu-rasterization` → `--disable-gpu-rasterization` (or software compositing). Removes the entire GPU-context-loss mode. **Doubles as the hypothesis test:** if the freeze vanishes with GPU raster off, cause confirmed.
2. **Resilience** (Ralph): a kiosk watchdog that restarts `eclipse-dashboard` when the renderer wedges — the UI must never silently freeze (honest-instrument).
3. **Page-side** (Iris): gate the two `infinite` animations to run only when the ribbon/alarm is actually active; drop unneeded `will-change`. Reduces the pressure that triggers the context loss.
4. **Optional headroom** (Ralph): raise CMA (`cma=256M`) — complements #1, does not fix it alone.

## Immediate mitigation APPLIED
`sudo systemctl restart eclipse-dashboard` (CIO-directed) → fresh GPU context: new chromium PIDs, CPU 39/31/24% → 18/9/8%, **0** ring-buffer errors post-restart, load falling. Screen restored. **Will re-freeze under sustained animated-carousel use until fix #1 lands.**

## Verification path (when the fix lands)
Re-run on the bench under sustained carousel navigation: `journalctl -u eclipse-dashboard | grep -c AllocateRingBuffer` stays ~0 and chromium CPU stays low over a multi-minute interaction session. This is a bench gate — does not need the car.
