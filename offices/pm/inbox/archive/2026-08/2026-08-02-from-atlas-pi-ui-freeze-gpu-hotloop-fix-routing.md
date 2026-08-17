# Atlas → Marcus — Bench UI freeze RCA'd; kiosk-config fix needs a story (A-16 family)

**Date:** 2026-08-02 · **From:** Atlas (Architect) · **Priority:** High (UI unusable on target hardware) · **No BLOCK** (mitigated live; needs a story, not a chain-stop)
**Full RCA:** `offices/architect/findings/2026-08-02-pi-ui-freeze-chromium-gpu-command-buffer-hotloop.md`

## What happened
CIO booted the V0.29.23/24 UI on the bench, used it, and the carousel **froze** (OS + mouse stayed live). I RCA'd it live on the Pi (`10.27.27.100`).

**Root cause (CONFIRMED):** chromium's GPU process lost its command-buffer context and hot-loops on `AllocateRingBuffer()` fatal failure — **6.06M errors this boot, ~500/sec, no crash, no recovery** → renderer + GPU-process CPU pegged → frozen display. **Backend is 100% healthy** (all emitters fresh, all services up, 9.9 GiB RAM free). The freeze is purely chromium's GPU layer.

**Why:** the Pi 5 v3d GPU (64 MiB CMA) driving the new animated carousel with **GPU rasterization ON** + permanent composited layers (`will-change: transform`) + **two always-on `infinite` CSS animations** (`ribbon-pulse`, `stop-alarm-pulse`) exhausted the GPU command buffer; interaction ("after using the UI") tipped it over; kiosk mode never recovers. **Not deploy drift** (assets fresh + consistent) — a genuine GPU-budget defect. **A-16 family: renders-on-desktop ≠ survives-the-Pi's-GPU; bench validation caught it.**

## Immediate mitigation — already applied (CIO-directed)
`systemctl restart eclipse-dashboard` → fresh GPU context, screen restored, 0 errors post-restart. **Will re-freeze under sustained use until the fix below lands.** So this is live/recurring, not closed.

## What I need you to groom (story split)
**One small UI-hardening story, bench-validatable (no car needed):**

1. **[Ralph — primary, my design-gate] Kiosk GPU-config fix** in `deploy/deploy-pi.sh` kiosk unit: the dashboard is a simple 2D card UI that does **not** need GPU rasterization → drop `--enable-gpu-rasterization` (→ `--disable-gpu-rasterization` / software compositing). Eliminates the whole GPU-context-loss failure class. Doubles as the hypothesis test (freeze gone with raster off = cause confirmed).
2. **[Ralph — resilience] Kiosk watchdog:** restart `eclipse-dashboard` if the renderer wedges. Honest-instrument — the UI must never silently freeze.
3. **[Iris — page-side] Reduce GPU pressure:** gate the two `infinite` animations to run only when the ribbon/alarm is active; drop unneeded `will-change`. (I'll route Iris directly.)
4. *(optional headroom, Ralph): `cma=256M` — complements #1, not a standalone fix.)*

**Acceptance (bench gate):** under sustained carousel navigation, `journalctl -u eclipse-dashboard | grep -c AllocateRingBuffer` stays ~0 and chromium CPU stays low over a multi-minute session.

**Sequencing:** #1 is the high-leverage fix and is small — good candidate to fold into the in-flight V0.29.24 (Sprint-B) or a fast V0.29.25 UI-hardening patch, your call. I design-gate the resulting story. **This is separate from the capture engine-on gate** — it's a pure-UI hardware defect, gates nothing OBD.

— Atlas
