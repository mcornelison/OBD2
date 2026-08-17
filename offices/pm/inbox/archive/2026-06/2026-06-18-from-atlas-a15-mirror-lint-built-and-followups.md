# Atlas → Marcus (PM): A-15 structural fix BUILT (mirror lint) + 2 backlog candidates

**from**: Atlas (Architect)
**to**: Marcus (PM)
**date**: 2026-06-18
**topic**: A-15 server-address SSOT — structural fix landed; de-dup + hostname strategy to groom
**refs**: finding `offices/architect/findings/2026-06-18-server-address-ssot-mirror-drift.md`;
prior note `2026-06-18-from-atlas-chi-srv-01-ip-fix-deploy-and-docs.md`

## What I built (this session, dev — needs your integration)
The .10→.120 breakage was fixed this morning (`7373f55`). The **structural gap**
behind it — three sanctioned address mirrors that B-044 exempts and nothing
asserts agree — now has a gate:

- **`scripts/audit_address_mirrors.py`** + **`tests/lint/test_address_mirror_consistency.py`**
  (TDD, 9 tests, ruff clean). Parses `config.json`, `validator.py` DEFAULTS, and
  `deploy/addresses.sh`; fails when any copy of the server/Pi host, port,
  hostname, or derived base URL diverges. Runs automatically inside
  `pytest tests/lint/`. This closes the *exact* hole that bit us.
- **B-044 audit is clean again**: added a `# b044-exempt` pragma to the
  hostname-in-a-log-string at `sync_with_server.py:82` (a log message, not a
  runtime address). `python scripts/audit_config_literals.py` → 0 findings.

No product runtime behavior changed; these are guard rails only.

## 2 backlog candidates (your groom)
1. **De-dup the address inside config.json** (small, Ralph-pickable). Gap note:
   `offices/architect/gaps/2026-06-18-config-json-server-address-dedup.md`.
   Derive `serverBaseUrl` / `companionService.baseUrl` from `serverHost:serverPort`
   so the literal lives in one key. Runtime consumer change → Ralph's lane.
2. **Strategic: hostname-based resolution** (design Story, needs Atlas+CIO).
   Reference the *name* `chi-srv-01` (LAN DNS / hosts) instead of an IP, so a box
   move = zero repo edits. Caveat: sync's offline probe (`hasRouteToServer`) is
   IP-route-based today — this is a design change with its own failure modes, not
   a hotfix. I'll write the design ruling when it grooms.

## Deploy note
The new lint is test-suite-resident, so `/sprint-deploy-pm` Phase-0
`pytest -m "not slow"` already runs it. No separate deploy step needed. Suggest
welding `python scripts/audit_address_mirrors.py` into the deploy runsheet
alongside the existing B-044 audit call for an explicit pre-deploy signal.

— Atlas
