# TD-063 — Idle-card "last-drive" fact has no state-file source (degrades honestly)

- **Filed by:** Ralph (Rex), Sprint 61 (V0.29.15), during US-481.
- **Severity:** low (honest-instrument preserved; the fact just reads thin).
- **Type:** tech-debt / data-gap.

## What

The US-481 idle-state home card renders a 3-fact summary strip:
`last-drive · battery-with-age · honest-faults`. The **battery** and **faults**
facts have real state-file sources (`battery-health`, `dtc`). The **last-drive**
fact does NOT — there is no last-drive-summary state file the carousel can
consume. The system-status `drive` block only carries the *current* drive
(`{state, driveId}`), and the emitter writes `driveId: null` while idle. So on a
parked Pi the last-drive fact honestly reads **"No recent drive · since key-off"**
— which is honest (never fabricated) but not informative.

## Why it's out of US-481 scope

US-481 is a display/consumer story (scope: carousel.js / dashboard.html/.css).
Wiring a last-drive summary into a state file is an **emitter** change (the
US-480-a orchestrator-invoked emitter lane), not a display change. Inventing a
last-drive emitter inside US-481 would break the scope fence and step on the
US-480-a run-model. `idleLastDriveFact()` was therefore built to degrade
honestly and will render a real last drive the moment such a source appears
(the card is a pure consumer of the state-file shape).

## Suggested fix (future story)

Add a small `last-drive` summary to a state file (candidate source:
`drive_summary` table — last row's id / distance / duration / end-ts) written by
the orchestrator-invoked emitter path, then point `idleLastDriveFact()` at it.
The `drive_summary` data already exists (`src/pi/obdii/drive_summary.py`); it is
just not surfaced to the dashboard state dir. Ties to the retired pygame
`parked_mode.py` DriveSummary (US-485 sunset) — the carousel is the successor
surface and should carry the same last-drive readout.

## Grounding

- `src/pi/splash/system_status_emitter.py` — `drive` block = `{state, driveId}`,
  `driveId=None` when idle (line ~137/147).
- `src/pi/display/screens/parked_mode.py:123` — the legacy pygame surface's
  `driveSummary` (last drive session summary) — the capability being sunset.
- `src/pi/obdii/drive_summary.py` — the `drive_summary` table (the data exists).
