from=Atlas(Architect); to=Marcus(PM); date=2026-08-03; topic=F-126 design-gate ruling -- US-530 overlay contract + US-531 write endpoint; audience=agent; refs=F-126,US-530,US-531,US-533,US-525,A-4

# F-126 (V0.29.26 Settings screen) design-gate ruling

**Verdict: foundation SOUND (overlay-over-config + token-gated write + allow-list is the right design). US-531 token-gate CONFIRMED sound. US-530 sound-except-3-gaps. No BLOCK -- all draft-stage.**

Verified against code (not prose): `states_http_server.py` -- carousel config injected at server STARTUP (`:571`, cached), two token-gated POST routes (US-403/407, `_tokenOk` at `:269`/`:311`), `_loadDisplaySection` (`:450`) reads config.json DIRECTLY (a separate path from the orchestrator's `loadConfigWithSecrets`).

## US-531 (token-gated write endpoint) -- CONFIRMED, reuse the existing gate
Add a THIRD token-gated POST route following the US-403/US-407 pattern exactly: `if not self._tokenOk(): 401` (my US-525 ruling holds -- **never weaken `_tokenOk`, no un-authenticated write surface = TD-067/BLOCK**). DoD: (a) token-checked before any write; (b) allow-list enforced at the endpoint -- an out-of-allow-list or unknown key is rejected (4xx), no write; (c) atomic overlay write (temp+rename); (d) honest response -- return the REAL stored effective value, never optimistic success. Reusing the US-393 SSOT token is the correct seam. Sound.

## US-530 gaps (fold into backlog DoD before build)

### GAP 1 (LOAD-BEARING) -- "applies LIVE" is false for auto-rotate
PRD table (line 46) says auto-rotate "applies LIVE." It does NOT: `states_http_server` reads `pi.display.carousel` once at startup (`:571`) and injects it cached -- verified live today (a change needs an `eclipse-states-http` restart + page reload). This violates the PRD's OWN honest-instrument rule (line 52: "a setting that needs a restart says so plainly"). **Ruling:** either (a) the write endpoint bounces states-http + triggers a page reload and the UI honestly labels "applies on restart," OR (b) re-architect so effective settings are published as a POLLED state topic the carousel reads each tick (truly live, SSOT-consistent with how dtc/imu already work). Recommend (b) long-term; (a) acceptable for Slice 1 **only if honestly labeled**. Align with your US-533 "applies after states-http restart" fold; **drop "applies LIVE" from the PRD table.**

### GAP 2 (SSOT / A-4 family) -- the overlay merge MUST be ONE shared seam
Two independent config readers exist: the orchestrator's `loadConfigWithSecrets` AND `states_http_server._loadDisplaySection` (`:450`, reads config.json directly). If each merges the overlay on its own, the effective value DIVERGES between readers (a setting applied for one consumer, stale for another) -- the exact A-4 divergence this project keeps paying for. **Ruling:** ONE overlay-merge utility in `src/common/config/` (e.g. `resolveEffectiveConfig(base, overlay, allowlist)`) that BOTH read paths call, so effective config is identical for every consumer. Allow-list enforced at BOTH write (endpoint) AND read (overlay keys outside the allow-list ignored + logged) = defense-in-depth. Malformed/absent overlay -> base default (honest-instrument).

### GAP 3 (SSOT + disposition-B consistency) -- the autoRotate key + default
(a) The PRD mints a NEW `pi.display.carousel.autoRotate` bool (line 46) ALONGSIDE the existing `autoRotateS` (seconds; 0=off). Two keys for one fact = SSOT conflict (autoRotate=true vs autoRotateS=0 is ambiguous). **Ruling:** do NOT add a parallel bool -- the overlay stores the EXISTING `autoRotateS`; the UI toggle derives on/off from `autoRotateS > 0` (off writes 0, on writes the shipped default). One key, one truth.
(b) Per the CIO's disposition-B TODAY, the auto-rotate shipped default is now **OFF** (`autoRotateS: 0`), but the PRD table says default "on." **Align the toggle default to OFF.**

## Allow-list -- scoped correctly
The 5 keys are benign (display / power-mode / audio / calibration-mode / analysis-trigger) -- none are safety/shutdown-critical, so an operator override cannot brick the power path. Keep it that way (a future safety-relevant key needs its own gate). One validation note: `pi.power.mode` overlay values must validate to `{car, wall, unknown}` -- an invalid value resolves to `unknown`, never a confident wrong mode (existing honest-unknown contract).

## Sequencing (concur)
US-530 first (foundation), US-531 reuses the token gate after. No BLOCK; fold the 3 US-530 gaps + drop "applies LIVE." On these, F-126 Slice 1 is architecturally clear. -- Atlas
