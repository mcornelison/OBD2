---
name: feedback-deploy-validation-distinct-gate
description: Code merged to dev + Rule-13 PASS does NOT mean it renders/works on hardware; deploy/bench validation is a separate gate that must run before sprint/chain validation.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 57f4d416-489f-4f2f-ad76-90102e0e7a58
---

The V0.29 F-103 splash + F-092 carousel were code-complete, merged to `dev`, and Atlas Rule-13-signed (code-honors-contract) across Sprints 48/49 — yet the Pi's 3.5" display was **blank on the first real boot** (2026-07-01, V0.29.4). Root cause: `deploy-pi.sh` installed the UI *assets + backend* (state server on :9899) but **never ran the kit installers that install the chromium kiosk units**; plus three hardware-only bugs only visible on the panel — an SSH-tty session-detection abort, `chromium-browser`-vs-`chromium` (Trixie), and DPMS 10-min screen-sleep ("no input"). All fixed in `deploy/deploy-pi.sh` (`step_install_ui_kiosk_units`) + `deploy/eclipse-kiosk-no-blank.conf`, validated end-to-end (teardown → full deploy → real power-cycle → splash rendered).

**Why:** "merged to dev" and "Rule-13 PASS" both validate CODE against the contract. Neither exercises the *deploy path on real hardware*. The "bench validation" of Sprints 48/49 was exactly the gate meant to catch this class — it was deferred, so the gap shipped silently and only surfaced when the CIO rebooted.

**How to apply:** Treat **deploy/hardware/bench validation as a gate DISTINCT from code-fidelity Rule-13.** Do NOT `/sprint-validated` a display/deploy-touching sprint, and do NOT `/chain-validated` a chain, until the artifact renders/works **end-to-end from a clean `deploy-pi.sh` on the actual hardware** (for UI: reboot + confirm the screen; for deploy steps: teardown → deploy → verify). Also: hardware-only failure modes (session type over SSH reads `tty`; distro binary-name drift; DPMS/screen-blank) never show in unit/DOM tests — plan a real on-device pass. Extends [[feedback-runtime-validation-required]] from runtime-only bugs to deploy/hardware rendering. Related: [[feedback-data-over-external-indicators]].
