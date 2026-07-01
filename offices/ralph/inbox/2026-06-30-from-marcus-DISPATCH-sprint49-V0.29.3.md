from=Marcus(PM); to=Rex(Dev); date=2026-06-30; topic=DISPATCH Sprint 49/V0.29.3 -- Pi touch-carousel dashboard + DTC viewer (bench-only, 9 stories); audience=agent; urgency=high; refs=US-399,US-400,US-401,US-402,US-403,US-404,US-405,US-406,US-407

# Marcus -> Rex: Sprint 49 / V0.29.3 DISPATCHED

Branch **`sprint/sprint49-V0.29.3`** forked from `dev`, pushed, upstream set; checkout is on it. **Atlas design-gate SIGNED OFF** (A-1..A-8 + DTC rulings). **9 stories** -- big sprint; pace yourself.

## Contract
`offices/ralph/sprint.json` -- sprint 49, V0.29.3, 9 stories. Frozen; do not edit the contract. Builds on **F-103 (V0.29.2, on dev)** -- reuses its chromium kiosk + `eclipse-states-http` + token + states-dir.

## Build order
**Carousel first** (US-399 is the foundation the rest extend):
1. **US-399 carousel shell** -- **start here.** Dashboard kiosk + swipe + persistent top bar + **extend `eclipse-states-http` to full runtime** + touch.
2. **US-400 System Status card** + emitter (deps US-399) -- the I-033 BT-reconnect-visibility fix.
3. **US-401 Battery Health card** + emitter (deps US-399) -- **LOCK the 2 render-breaking traps**: (a) SoC% from the MAX17048 register ONLY, never lerp from voltage (`3.44 V` not `3.44 %`); (b) GREEN always carries "last health check (age)". Cell = Pi UPS battery, never "vehicle". Ladder only when `draining:true`.
4. **US-402 pygame sunset** (deps US-400+401) -- parity-gated; never both surfaces at once.
5. **US-403 System Setup menu** (deps US-399) -- gated service control via the **A-7 polkit privilege path (kiosk NEVER root)**; `eclipse-powerwatch` restart-only; confirm-before-consequential.

**DTC viewer** (Card 5, builds on the carousel shell):
6. **US-404 DTC KOEO read + `dtc` emitter** (deps US-399) -- key-on Mode 03(+07) on the **OBD connection-edge** (`event_router` onConnectionRestored), gated on no RUNNING drive, owned by the DTC capture path NOT DriveDetector; **`drive_id = NULL` stamped EXPLICITLY** (not getCurrentDriveId -- avoids a stale-open leak). The 3 emitters (system-status/battery-health/dtc) ride the F-103 states-dir provisioning (C-5; don't re-invent).
7. **US-405 takeover + ribbon** (deps US-404).
8. **US-406 Alerts card + detail** (deps US-404) -- severity-gated fix (red/yellow = diagnose-don't-swap, green = fix + trust badge); realtime_data fallback (Mode 02 dead on MD326328).
9. **US-407 DTC Clear (Mode-04) -- LOAD-BEARING vehicle-write, LAST** (deps US-406). **Renders against `offices/tuner/dtc-display-clear-safety-advisory.md` (Spool SSOT, NON-NEGOTIABLE -- you render against it, you do NOT redefine it).** Gate = all-MINOR + logged + server-acked; confirm modal; **immediate re-read to prove cleared**; session-lock; **the gate is RE-CHECKED at the privileged action path, NOT trusted from the UI**. Clear via the same polkit pattern as US-403.

## Validation = BENCH ONLY (CIO waived drive reqs)
Fixture/DOM tests + Pi bench drills (cold-reboot handoff, swipe, BT-drop rig, UPS-drain rig, long-press, mock/real systemctl). DTC: fixtures + a real KOEO read of the already-set drive-27 **P0443** (read, do NOT clear before reading) + Mode-04 clear proven on a real MINOR. NO drive drills.

## Notes
- Commit to THIS branch (shared-checkout: commit-immediately, never push-to-main; I integrate at close).
- Iris owns the UI design (specs `docs/superpowers/specs/2026-06-05-pi-touch-carousel-*` + `*-dtc-*`); Atlas owns the architecture (A-1..A-8 signed off 2026-06-30).
- 9 stories is large -- if you find yourself compressing on the DTC line, flag it and I'll consider splitting 49a (carousel)/49b (DTC).

CIO launches `ralph.sh` from his shell.

-- Marcus
