# chi-srv-01 IP move (.10 → .120): repo FIXED, but DEPLOY + doc updates owed

**Date**: 2026-06-18
**From**: Atlas (Architect)
**To**: Marcus (PM)
**Priority**: HIGH (running system is currently pointing at a dead address)

## What happened
CIO relocated chi-srv-01 to `10.27.27.120`; `.10` is dead (verified: `.120` replies ~5 ms,
`.10` destination-unreachable). Repo had `.10` in the canonical config + several functional
sites, so the Pi's sync / Ollama / update paths target a dead host. CIO directed the fix.

## Repo fix — DONE (commit `7373f55` on `dev`)
All functional + canonical sites → `.120`: `config.json` (serverHost / serverBaseUrl /
companionService.baseUrl), `validator.py` DEFAULTS, `deploy/addresses.sh`,
`.env.production.example`, coupled tests, stale docstrings. Verified: validate_config OK,
config-validator 47/47, migration tests 53/53, zero `.10` literals repo-wide outside `.md`.

## Owed — your lane

1. **DEPLOY (urgent).** The fix is in the repo only. The *running* Pi + chi-srv-01 still have the
   old config deployed → **sync is failing right now.** Need a redeploy from `dev` to both targets
   (or a direct hotfix of the deployed `config.json`). **Also:** the Pi's actual on-box `.env`
   (not in repo) likely still has `OLLAMA_BASE_URL=...10...` — update it to `.120` on the box if
   AI is enabled (config shows `server.ai.enabled=false`, so may be moot, but check).
2. **Docs (PM-owned — I did NOT edit your files).** Stale `.10` for chi-srv-01 in:
   - `offices/pm/roadmap.md:111` (infra table)
   - `offices/pm/projectManager.md` (network table mixed: line 276 already says `.120`, others `.10`)
   - `offices/pm/tech_debt/TD-006-*.md`
   Also `offices/tester/tester.md` (several) — I'll send Argus a separate note.
   And shared memory `MEMORY.md` "Key Infrastructure" line + `roadmap` still say `.10`.
3. **Backlog (SSOT hardening).** This drifted because the SSOT is actually *three* sanctioned
   mirrors (config.json + validator DEFAULTS + addresses.sh) that must move together, and the
   B-044 audit exempts all three — so mirror-drift is unguarded. Finding +
   recommendations (a cheap mirror-consistency lint; de-dup within config.json; optional
   hostname-based resolution) in `offices/architect/findings/2026-06-18-server-address-ssot-mirror-drift.md`.
   Suggest a small E-OPS / tech-debt Story to add the mirror-consistency check.

— Atlas
