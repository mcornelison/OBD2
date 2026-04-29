# TD-037: Stale `deploy/obd2-server.service` + `deploy/install-server.sh` (pre-US-231)

| Field      | Value                                                              |
|------------|--------------------------------------------------------------------|
| Priority   | Low                                                                |
| Status     | Open                                                               |
| Category   | infrastructure                                                     |
| Affected   | `deploy/obd2-server.service`, `deploy/install-server.sh`           |
| Introduced | 2026-04-16 (early server-deploy work, never reached production)    |
| Created    | 2026-04-28                                                         |
| Filed By   | Rex (Ralph Agent 1) Session 105 / US-231                           |

## Description

Two files in `deploy/` predate US-231 and contain wrong defaults that will
trip up any operator who finds them and tries to use them:

### `deploy/obd2-server.service` (note: name has a `2`, not the US-231 file)

| Field | Stale value | Reality / US-231 value |
|-------|-------------|------------------------|
| `WorkingDirectory` | `/home/mcornelison/Projects/OBD2v2` | `/mnt/projects/O/OBD2v2` (per `addresses.sh SERVER_PROJECT_PATH`) |
| `ExecStart` venv | `.venv/bin/uvicorn` | `/home/mcornelison/obd2-server-venv/bin/uvicorn` |
| `After=` deps | `mysql.service` | `mariadb.service` (Debian 13 trixie names it `mariadb.service`) |
| `Restart` | `on-failure` | `always` (US-231 spec; mirror of US-210 Pi-side) |
| Logs | `StandardOutput=append:.../logs/server.log` | `journalctl -u obd-server` is single source of truth |
| `RestartSec` | `10` | `5` (US-231 spec) |
| Flap protection | `StartLimitIntervalSec=300 / StartLimitBurst=5` in [Service] | belongs in [Unit] (modern systemd warns in [Service]) |

### `deploy/install-server.sh`

A standalone bash installer using `sed` to template the unit file. Pre-US-231
it was the alternative to `deploy/deploy-server.sh`. Issues:

- Hardcoded default `INSTALL_PATH=/home/mcornelison/Projects/OBD2v2` -- wrong path on the actual server
- Inlines paths via sed mutation of the unit file at install time (fragile pattern -- the new US-231 unit uses a static template + EnvironmentFile for runtime values)
- Defaults to `obd2-server` service name (not `obd-server` per US-231 spec)
- Will install the stale unit file content on top of any properly-installed US-231 unit if invoked

## Why It Was Accepted

US-231 is strictly scoped to the new `deploy/obd-server.service` + the
`deploy/deploy-server.sh` install step. Per CIO Q1 rule (drift outside sprint
scope -> file TD immediately, do not auto-fix), these stale files are out of
US-231's filesToTouch list and were left untouched. Filing this TD as the
loud handoff to Marcus for a future sweep.

## Risk If Not Addressed

**Low.** The stale files won't be invoked by `deploy-server.sh` (which uses
the new `obd-server.service` name, not `obd2-server.service`), and CIO
runs deploys via `deploy-server.sh` not the standalone installer. Risk is
limited to:

1. A future operator (or Ralph agent) discovers `install-server.sh` and runs
   it, which would install the wrong unit file content under the wrong
   service name -- breaking the production setup until corrected.
2. A future feature search for "server systemd unit" might surface the wrong
   file as the answer.

Both are low-likelihood given the documented surface in `specs/architecture.md`
§11 + `docs/testing.md` US-231 section now point to `obd-server.service` /
`deploy-server.sh` as the canonical paths.

## Remediation Plan

Sprint 19 candidate (S, low-prio cleanup):

1. Delete `deploy/obd2-server.service` (rendered obsolete by `deploy/obd-server.service`)
2. Delete `deploy/install-server.sh` (rendered obsolete by `deploy/deploy-server.sh step_install_server_unit`)
3. Search the codebase for references to `obd2-server` (the service name) and update any docs/comments to `obd-server`
4. Annotate this TD as Resolved with the commit hash that did the cleanup

A 30-minute cleanup story; Marcus's call whether it ships in Sprint 19 or
gets folded into the next "deploy hygiene" sprint.

## Related

- Story that filed: US-231 (Sprint 18, Sprint 18 server systemd unit)
- Canonical paths now in production:
  - `deploy/obd-server.service` (NEW unit file)
  - `deploy/deploy-server.sh step_install_server_unit` (NEW install step)
- Filed alongside the US-231 closeout because that's when the stale files
  were noticed during the install-pattern scout.
