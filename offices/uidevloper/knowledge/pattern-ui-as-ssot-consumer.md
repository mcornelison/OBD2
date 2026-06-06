---
name: pattern-ui-as-ssot-consumer
description: UI surfaces consume existing SSOTs from other domains; never invent their own state. Atlas's SSOT-design-pattern extends from system architecture to pixels.
metadata:
  type: pattern
---

When designing a UI surface that displays system state, the surface is a **consumer** of an existing SSOT, never an author of state. Apply Atlas's [[ssot-design-pattern]] to pixels:

1. Find which existing service owns the truth about the state you want to display (boot-progress instrument, ShutdownSequencer, eclipse-obd, etc.).
2. Define the contract: that service writes state to a known location (file / IPC endpoint / DB row); UI reads only.
3. UI polls or subscribes; UI never decides system condition. If the state file says `degraded=true`, UI paints degraded. UI doesn't independently check hardware.
4. UI escalates rendering on degradation but NEVER changes the underlying state model.

**Why:** Prevents drift between displayed state and actual state — the "green-when-broken" failure mode (UI says everything is fine; system is on fire). Single source of truth eliminates the diagnostic gap of "the dashboard says X but the data says Y." Argus's data-layer false-pass-class lessons (V0.27.7 / V0.27.16 / V0.27.17) apply equivalently at the pixel layer per his 2026-05-22 ack: "green-when-broken is a UI defect equally with test-passes-when-behavior-doesn't."

**How to apply:**
- Before designing any UI element that renders system state, identify the SSOT it consumes
- If the SSOT doesn't exist yet, that's an architectural item for Atlas — flag it, don't invent
- Test for failure case: "if the SSOT says X, does my UI render Y or X?" — must be X always
- Three reinforcing channels for honest-instrument escalation: color + motion-change + text (per B-103 design — degradation must be unambiguous even on narrow-gamut panels)

**Confirmed:** B-103 splash design 2026-05-26 — splash consumes two SSOTs (`/run/eclipse/boot-state` from boot-progress-finalize; `/run/eclipse/shutdown-state` from ShutdownSequencer). Splash never polls hardware. Atlas confirmed (2026-05-22 hello-ack) that "specs/UI/ tokens (color/type/iconography) under that [SSOT] pattern is correct precedent, not a one-off."

## Two safety-UI corollaries for consequential actions (DTC clear-code, 2026-06-05 — Spool-endorsed)

When the UI offers a **consequential / destructive action** (e.g. Mode-04 clear that wipes codes + freeze-frame + readiness monitors), two extra rules layer on top of "consume, don't author":

1. **Re-check the gate at the action path — never trust the UI's enabled state.** The button being enabled is convenience only; the actual action must re-verify its preconditions where it executes (server/service side), so a tampered or stale UI can't force it. Spool: "endorse — defense-in-depth." Mirrors the F-092 service-control privilege model.
2. **Override a dangerous suggestion by REPLACING it, not hiding it.** For a high-severity code the suggested-fix slot is *replaced* by a "diagnose, don't just swap parts" directive — not blanked. A hidden slot reads as "no info"; a replaced slot actively steers the human away from the wrong action. Spool: "exactly right." Design dangerous-content slots to be **replaceable by a directive**, not merely conditional-hidden.

Both confirmed in `inbox/2026-06-05-from-spool-dtc-viewer-confirm-plus-live-results.md` ("you rendered the SSOT faithfully… two of your calls improve on mine").

Related: [[pattern-argus-ui-acceptance-criteria]]; [[feedback-cio-architectural-paths-belong-to-atlas]].
