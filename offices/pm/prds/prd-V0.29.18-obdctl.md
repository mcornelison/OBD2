---
sprint: 64
version: V0.29.18
status: draft
createdAt: 2026-07-27
createdBy: Marcus (PM)
selectedStories: [US-492]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS
feature: F-122 (Pi operational tooling)
theme: On-Pi service-control maintenance CLI (obdctl) -- CIO high-priority
priority: HIGH (CIO-requested 2026-07-27)
atlasReview: "Not gated -- an ops CLI over systemctl on the existing deploy-installed units + the US-403 service_control.py SSOT + the D-7 powerwatch safety rule (all already-ruled). No new architecture. FYI to Atlas at close."
---

# PRD: V0.29.18 -- On-Pi service-control maintenance CLI (obdctl)

| Field | Value |
|---|---|
| Version | V0.29.18 (patch on `dev`) |
| Priority | **HIGH** -- CIO-requested |
| Theme | One command on the Pi to stop/start/restart/kill/status any OBD-project service or ALL, for maintenance + issue diagnosis |
| Status | DRAFT -- ready (grounded against the real Pi units + existing SSOT) |
| Lane | Pi ops tooling (bash/Python CLI + deploy install) |
| Stories | **US-492** under **F-122** (new, E-OPS) |
| Deploy + validate | Deploys from `dev`; validated by running `obdctl` on the Pi |

## Why now
CIO needs a maintenance/troubleshooting tool he can run **on the Pi** to control the OBD-project services independently or all at once -- servicing the system or working through issues without hand-typing `systemctl` per unit or remembering the full unit list.

## The story (full DoD/validationCriteria in `backlog.json`)
**US-492 -- `obdctl <action> <service|all>`** (status/start/stop/restart/kill), grounded in:
- **The real 8 Pi units** (verified 2026-07-27): `eclipse-obd`, `eclipse-powerwatch`, `eclipse-states-http`, `eclipse-boot-state`, `eclipse-dashboard`, `rfcomm-bind`, `splash-boot`, `splash-grace`.
- **One SSOT for the unit list** -- extend/share the US-403 `service_control.py SERVICE_ALLOWLIST` (or a shared manifest) so it can't drift from what deploy installs.
- **Safety (load-bearing):** `eclipse-powerwatch` is the safe-shutdown guard (D-7/F-7: never leave it stopped). stop/kill of powerwatch (directly or via `all`) → loud warning + explicit confirm/`--force`; restart/status unrestricted. `kill` (SIGKILL) requires explicit intent, never a `stop` fallback. Bare invocation = status (no destructive default).
- **Honest output:** per-unit before→after state + OK/FAIL; `all` acts in sensible dependency order + prints a summary; not-installed units reported, not crashed.
- **Deploy-installed** (deploy-pi.sh) so it's on the Pi after a deploy.

## Not in scope
- The gated live-motion UI line (Sprint B) + the `--destructive` token residual -- unaffected, tracked separately.
