# US-394 shipped — F-103 ShutdownSequencer phase-emit hook + architecture.md §10.6.1

**From:** Rex (Dev) → Marcus (PM)
**Date:** 2026-06-29
**Sprint:** 48 / V0.29.2 · Story: US-394 (F-103 shutdown splash, producer side)
**Status:** `passes: true` — committed to `sprint/sprint48-V0.29.2`

## What landed (the shutdown-state PRODUCER side)

- **`src/pi/splash/shutdown_state_emitter.py`** (NEW) — pinned spec §6 schema
  builder + `makeShutdownPhaseEmitter` best-effort writer (atomic, reuses
  `ensureStatesDir`/`writeStateAtomic`; a write failure is logged, never raised).
- **`ShutdownSequencer` phase-emit hook [A-2]** (`controller.py`) — optional
  generic `phaseEmitFn` emitted at each transition: `grace` (T=0, before
  smoothing resolves) → `cancelled` (smoothing fail / late power-return) |
  `flushing` (pipeline) → `powering_off` (before `systemctl poweroff`;
  VCELL-floor fast-path emits `powering_off` with no `flushing`, honest
  instrument). Phase constants live in `controller.py` (sequencer = SSOT of
  phase); splash IMPORTS them — strictly unidirectional (spec §6/§481). When the
  hook is unwired the sequencer runs the **byte-identical legacy path** (no extra
  `isOnBattery()` read — regression-guarded).
- **[A-6] timing invariant** in the `controller.py` module docstring (verbatim
  per spec §469-479).
- **Wired** in `__main__.py` (gated on `pi.splash.enabled`; states dir from
  `pi.splash.statesDir`).
- **Rule-10 DoD:** `specs/architecture.md` **§10.6.1** documents the hook, the
  phase table, the A-2 constraints, the A-6 timing invariant, and the C-5
  shutdown-state-survives-eclipse-obd-stop guarantee. Forward-ref in the F-103
  subsection updated to a cross-ref.

**C-5:** already satisfied by US-393's units (`eclipse-states-http.service` shares
`RuntimeDirectory=eclipse-obd` + `RuntimeDirectoryPreserve=yes`; tmpfiles.d
recreates `states/` every boot) — no unit change needed; documented in §10.6.1.

## Gates
- `pytest tests/pi/splash tests/pi/power` = 108 passed, 1 skipped (POSIX-perms
  test skips on Windows). New: 5 emitter tests + 7 sequencer-hook tests.
- `ruff check` clean on all touched files.
- mypy + full-suite deferred to PM integration (slow SMB share; code is
  mypy-strict-shaped — same carve-out as US-393).

## ⚠️ Scope seam you need to know (US-394 vs US-396)

US-394's TITLE is the **producer** ("phase-emit hook + architecture.md §10.6").
I deliberately left the **render side** to **US-396**:

- shutdown kiosk render: `shutdown-state-poll.js` (NEW), `shutdown.html` D-1 fix
  (load `splash-shutdown.svg`), and the `splash-grace.service` + `splash-grace.path`
  trigger units (D-2: retire the self-cancelling `splash-shutdown.service`).
- V-1/V-2 install-time checks; confirm D-1/D-2/D-3 repros don't reproduce.

US-396 is explicitly allowed to fold those. **The BENCH shutdown-render drill
(validationMethod) needs BOTH US-394 + US-396 in place** — please sequence the
bench drill after US-396 lands. US-394 alone makes "ShutdownSequencer emits phase
events [A-2]" true and dev-box-verifiable; the visual render is US-396.
