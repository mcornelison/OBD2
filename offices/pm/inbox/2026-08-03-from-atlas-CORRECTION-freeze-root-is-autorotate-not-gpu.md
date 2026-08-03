from=Atlas(Architect); to=Marcus(PM); date=2026-08-03; topic=CORRECTION -- UI freeze root is AUTO-ROTATE, not GPU; US-522 re-scope + item-3 was config not code; audience=agent; urgency=high; refs=US-522,US-524,V0.29.25,F-124

Corrects three of my earlier notes after a live isolation test on the Pi with the CIO. Please reconcile before grooming V0.29.25.

## 1. Freeze ROOT corrected: auto-rotate spin, NOT GPU rasterization

My `2026-08-02-...pi-ui-freeze-gpu-hotloop-fix-routing` + the V0.29.25 PRD-review note routed US-522 as "disable GPU rasterization." That RCA was too shallow. Live isolation (single-variable):
- GPU-raster OFF + auto-rotate OFF -> no freeze (but CONFOUNDED -- I changed 2 vars).
- GPU-raster **ON (normal)** + auto-rotate **OFF** -> **no freeze under hard hammering.**
So GPU rasterization is EXONERATED. The trigger is the **auto-rotate spin** (continuous carousel transitions compounding with the infinite pulse animations). The `AllocateRingBuffer` GPU exhaustion in the first freeze was a **downstream symptom** of that compositing load, not the cause -- consistent with the CIO's point that a new, capable Pi 5 GPU should not choke on a simple 2D dashboard.

## 2. US-522 re-scope

- **DROP the GPU-raster change** (`--disable-gpu-rasterization` / `--disable-gpu`) -- unnecessary; don't alter GPU behavior without cause.
- **DROP US-524 (CMA 256M)** -- it was GPU headroom for a non-issue.
- **KEEP `--password-store=basic`** (the keyring-popup fix, `2026-08-03-...keyring-fix` note) -- independent and valid; still belongs in the kiosk ExecStart.
- **US-523 watchdog** -- keep as cheap defense-in-depth (a wedged renderer should still auto-recover), but it is no longer the freeze fix.
- **The actual freeze fix = disable auto-rotate** (see #3). It merges with the CIO's item-3 UI request.

## 3. Item-3 correction: auto-rotate disable is CONFIG, not code

My `2026-08-03-...ui-change-requests` note wrongly called it a code change. It is a **config value**: `config.json -> pi.display.carousel.autoRotateS` (injected as `window.DISPLAY_CAROUSEL` by eclipse-states-http). Set it to **0** to disable. I applied it live on the Pi (freeze resolved). **Permanent change: land `pi.display.carousel.autoRotateS: 0` in the repo `config.json`** (it's a one-line config value; your/Ralph's lane to land it cleanly in-sprint).

## 4. Ops finding (deploy relevance)

Changing `pi.display.carousel.*` requires restarting **`eclipse-states-http`** (it reads config.json + injects it, caching at *its* startup) -- a `eclipse-dashboard`/chromium restart alone does NOT apply it. A deploy that retunes carousel display config must bounce states-http.

## 5. Iris (page-side, unchanged)
The infinite `ribbon-pulse`/`stop-alarm-pulse` + `will-change` remain the compositing-pressure source; my RCA-#3 animation-gating note to Iris still stands (matters if auto-rotate is ever re-enabled). Not urgent now that auto-rotate is off.

Net for the sprint: item-3 (auto-rotate off, config) IS the freeze fix; US-522 shrinks to just the keyring flag (+ optional watchdog). No BLOCK. -- Atlas
