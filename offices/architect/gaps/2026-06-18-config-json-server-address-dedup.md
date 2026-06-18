# Gap — de-duplicate the server address within config.json

**Date**: 2026-06-18
**Author**: Atlas (Architect)
**Type**: developer-pickable (small)
**Relates to**: Watch item A-15; finding `2026-06-18-server-address-ssot-mirror-drift.md`

## Problem
`config.json` encodes the *same* server address three times:
- `server.network.serverHost` = `10.27.27.120`
- `server.network.serverBaseUrl` = `http://10.27.27.120:8000`
- `pi.companionService.baseUrl` = `http://10.27.27.120:8000`

All three must be hand-edited together on a box move. The new A-15 lint
(`scripts/audit_address_mirrors.py`) now *guards* this (it fails if the derived
URLs don't match `serverHost:serverPort`), but guarding duplication is weaker
than removing it.

## Desired end state
The address literal lives in **exactly one** config key; the base URLs are
*derived* in the consumer.

- Keep `server.network.serverHost` + `serverPort` as the single literal.
- Derive `serverBaseUrl` and `pi.companionService.baseUrl` at load time
  (`f"http://{serverHost}:{serverPort}"`) instead of storing them.

## Constraints / care
- This is a **runtime consumer change** (whoever reads `companionService.baseUrl`
  / `serverBaseUrl` must tolerate the value being derived). Trace consumers:
  `src/pi/sync/*`, `validator.py` `_validateCompanionService`, any health/ping
  path. That's why this is routed to Ralph, not done by Atlas — it changes
  product behavior, not just a gate.
- Once derived, the A-15 lint's intra-config checks can be tightened (or the
  derived keys dropped from the comparison entirely).
- `validator.py` DEFAULTS still mirrors `companionService.baseUrl`
  (`validator.py:215`); decide whether it derives too or keeps the literal with
  the existing `# b044-exempt` pragma + A-15 cross-check.

## Acceptance
- `config.json` holds the server IP in one place.
- `python scripts/audit_address_mirrors.py` exits 0.
- Existing sync/companion tests stay green.

— Atlas
