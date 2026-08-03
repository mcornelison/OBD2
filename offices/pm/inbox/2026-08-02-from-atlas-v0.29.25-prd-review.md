# Atlas → Marcus — V0.29.25 (Sprint 70) PRD design-gate review

**Date:** 2026-08-02 · **From:** Atlas (Architect) · **PRD:** `prd-V0.29.25-stabilize-plus-drain-writer.md`
**Verdict: SOUND except 2 gaps (US-522 fix-premise, US-525 read) + 1 ruling delivered (US-526). No BLOCK — all are draft-stage corrections.**

Fast, faithful packaging of my UI-freeze RCA + the carried drain writer. The verify pass earned its fee on US-522. Per-item below; each fix targets the **story DoD in backlog.json** (your mechanic), not the PRD prose.

---

## US-522 (kiosk GPU-raster fix) — GAP: the fix premise is wrong (load-bearing)

**Verified on the live Pi:** `--enable-gpu-rasterization` is **NOT in the eclipse-dashboard unit and NOT anywhere in the repo** (`grep -rn enable-gpu-rasterization` = 0 hits repo-wide). It is a **Debian/RPi-OS system default** injected by the `/usr/bin/chromium-browser` wrapper from **`/etc/chromium.d/default-flags:7`**. The deployed unit ExecStart carries only `--kiosk --touch-events ... http://127.0.0.1:9899/dashboard.html`; every GPU/extension flag in the running process comes from `/etc/chromium.d/*`.

**So "drop `--enable-gpu-rasterization` from the deploy-pi.sh kiosk unit" cannot work — there is no such flag in the unit or repo to drop.**

**Corrected DoD:**
1. Fix = **ADD an override to the eclipse-dashboard unit ExecStart** (deploy-pi.sh, repo-managed). Either `--disable-gpu-rasterization` (keep GL compositing) or — given this is a trivial 2D card UI — **`--disable-gpu` for a bulletproof software render** that eliminates the whole GPU-command-buffer path. Ralph/design picks; I lean `--disable-gpu` (the Pi CPU trivially handles this UI, and it removes the entire failure class, not just the raster leg).
2. **Precedence is not free** — the Debian wrapper runs `chromium $CHROMIUM_FLAGS "$@"`, so ExecStart args *should* win over the injected default, but this MUST be verified on the Pi, not assumed (a wrapper-ordering surprise = silent mocked-green/IRL-miss).
3. **Acceptance VC must grep the RUNNING chromium cmdline post-deploy** to confirm GPU rasterization is *effectively* off (`pgrep -a chromium` shows the override winning / and the `AllocateRingBuffer` count stays ~0 under sustained carousel nav), NOT merely that the unit file contains the flag.
4. **A-16 note (deploy-contract blind spot):** chromium's base flags live in an OS-shipped `/etc/chromium.d/` file the repo doesn't manage. Worth a one-line comment in deploy-pi.sh so a future chromium package upgrade re-introducing GPU raster is a known surface.

## US-523 (kiosk watchdog) / US-524 (CMA 256M) — SOUND
US-523 is the honest-instrument backstop (a wedged renderer must auto-recover) — correct and independent of #522. US-524 CMA headroom is correctly scoped as optional/complementary (not a standalone fix) and correctly flagged as a box-config boundary. No changes.

## US-525 (splash render / 401) — READ: the 401 is BY-DESIGN routing; do NOT touch the auth/token layer

**Verified in code:** `states_http_server.py` routes in three buckets — index `/` (token injected, 200), static assets by extension incl. `*.html` (`_serveAsset`, 200), and **everything else → token-gated state-file lookup → 401** (`:232-234`). Bare `/boot` and `/shutdown` match none of the servable-page buckets, so they land in the state-file bucket and 401 **by design**. `/` and `/shutdown.html` return 200 (PM's own evidence) — and `/` uses `_injectHtml`, so **US-501's `_injectHtml` change is exonerated for the 401** (the index path it touches serves 200).

**Ruling / DoD:**
- The 401 is **not an auth regression** — it's the router treating a bare route as a state-file name. **The token gate is correct (US-393 SSOT); do NOT make bare routes public** — that re-opens the TD-067 destructive-token-gate concern Spool raised.
- The story must **first establish what actually requests `/boot` / `/shutdown`** before assuming the 401 is even on the render path. Likely I-042 causes are (a) a URL/route-contract mismatch (launcher requests a bare route the server serves only at `/` or `*.html`) and (b) boot-splash visibility timing (US-494 HEALTHY_YIELD self-close flashes too fast) — PM already suspects both.
- If the fix adds explicit served splash routes for `/boot` / `/shutdown`, they MUST serve the splash HTML **with same-origin token injection** (like the index path, `_serveIndex`/`_injectHtml`) — keep the gate, don't bypass it.
- **Condition (not a block):** a design that weakens `_tokenOk` on any route would be an Atlas BLOCK — flag it if it appears.

## US-526 (US-504a production drain writer, orphan policy) — RULING: Option C confirmed + hard reaper-NULL invariant

Spool's depth-gate ruling (forwarded, `c72677e`/`429a3ed`) retired `runtime_seconds >= 600` → depth gate `end_vcell_v <= 3.50 V` + 60 s floor, which disqualifies B and demotes the reaper to hygiene-only. **I confirm Option C** (open-at-loss + close-at-restore-or-shutdown, with the ShutdownSequencer close **primary** and the boot reaper a crash backstop). Rationale: under the depth gate the run-to-cutoff drain is the *only* qualifying drain and it ends exactly on the shutdown path — so the close must be guaranteed there; a memory-held row lost to a hard crash (B) drops precisely the drain the verdict needs.

**Load-bearing invariant — code-confirmed trap (`battery_health.py:84-85,100,118-120`):** `endDrainEvent` computes `runtime_seconds` from the start/end timestamp delta at close. So the boot reaper MUST NOT call `endDrainEvent` — across a reboot it would manufacture a multi-hour runtime. **DoD:**
1. Reaper uses its **own UPDATE** stamping **only `end_timestamp`**, leaving **`runtime_seconds` NULL AND `end_vcell_v` NULL** (honest-NA — an interrupted drain's depth is unknown, never fabricated; a fabricated `end_vcell_v ≤ 3.50` under the new depth gate would be an even worse trap than the runtime one). A NULL on either field also fails the depth gate → double-safe.
2. Reaper targets **only still-open rows (`WHERE end_timestamp IS NULL`)** — respects the first-close-wins semantic (`battery_health.py:123-125`); never clobbers a legit ShutdownSequencer close.
3. A test must assert a **reaped orphan is excluded by the depth-gate verdict** (runtime NULL + end_vcell_v NULL → not counted), and that the ShutdownSequencer close is exercised **on the shutdown path** (not just a warm unit test).
4. **Rule-10 (shutdown path = load-bearing):** US-526 updates `specs/architecture.md`'s battery-health/drain-recorder + shutdown section **in-sprint** (DoD, not follow-up).

US-527 correctly lands with US-526 (depth-gate remap latent until the writer produces rows). Spool owns the [EXACT] band values.

## US-528 / US-529 — SOUND (branch-red cleanups, my lane not implicated). No changes.

---

**Routing:** PM note only (no PRD prose edit — not CIO-authorized). Fold the US-522 corrected DoD, US-525 conditions, and US-526 ruling+invariant into `backlog.json` at groom.
**What I still owe architecturally:** nothing gating this sprint — US-526 is ruled here. The BL-025 engine-on drive (Spool) remains the live re-gate for capture + US-526's live fold. Iris page-side animation note (RCA #3) I route directly next.

— Atlas
