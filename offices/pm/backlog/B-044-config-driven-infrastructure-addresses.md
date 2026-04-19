# B-044: Config-Driven Infrastructure Addresses (Standing Rule)

**Priority**: Medium
**Size**: M (audit + sweep + standing rule + lint)
**Status**: Pending
**Epic**: B-037-adjacent (cross-cutting infra hygiene)
**Related**: Session 19 + Session 21 unresolved item (chi-srv-01 IP drift `.120` vs `.10`); commit `<TBD>` (this session's mass-rewrite remediation)
**Filed**: 2026-04-18 (PM Session 21, CIO directive)
**Source**: CIO directive

## Standing rule

**Infrastructure addresses (IPs, hostnames, ports, base URLs, MAC addresses) MUST live in config — never as string literals in source, tests, scripts, deploy, or specs.** Applies to both Pi and server tiers. Any new code or doc that references an address pulls it from `config.json`, environment variables (via `secrets_loader`), or a documented well-known fixture (e.g. `tests/conftest.py`). String-literal infrastructure addresses are the same class of bug as hardcoded credentials — they drift, they break across environments, and they require a global rewrite when the address changes.

## Trigger

Today's e2e validation (US-166 driver `scripts/validate_pi_to_server.sh`) failed because the script hardcoded `SERVER_HOST="10.27.27.120"`. The actual chi-srv-01 IP is `10.27.27.10`. The drift had been documented as a Session 19 "unresolved small item" and re-flagged in Session 21 — and was hiding in 32 files across the repo (src, scripts, tests, docs, configs, PM artifacts). A targeted global sed sweep fixed the immediate bug, but the underlying problem is that the address shouldn't have been a literal in the first place.

## Scope

### Phase 1 — Audit + categorize
Sweep every file for IP/hostname/port literals that name production infrastructure:
- `10.27.27.*` IPs (DeathStarWiFi LAN)
- `chi-eclipse-01`, `chi-srv-01`, `chi-nas-01`, `eclipse-tuner` hostnames
- OBDLink MAC `00:04:3E:85:0D:FB`
- Any port (8000 server, 22 SSH, 3306 MariaDB, 11434 Ollama)
Categorize each match into: (a) call-site that should read config, (b) doc/spec that should reference config, (c) test fixture that legitimately needs a deterministic value, (d) historical artifact (commit message, archived PRD, changelog) — leave as-is.

### Phase 2 — Centralize in config
- Promote all (a) and (b) cases to `config.json` under a new top-level `infrastructure` section (or extend the existing `pi.companionService.baseUrl` pattern):
  - `infrastructure.server.host`, `infrastructure.server.port`
  - `infrastructure.pi.host`
  - `infrastructure.pi.deviceId`
  - `infrastructure.obdLink.macAddress`
  - etc.
- Update `src/common/config/validator.py` defaults
- Update consumers — Python code reads via `config.get('infrastructure.server.host')`; bash scripts read via a tiny wrapper or `python -c 'json.load(open("config.json"))["infrastructure"]["server"]["host"]'`
- For tests: keep deterministic literals BUT define them once in a `tests/conftest.py` fixture (`SERVER_HOST = "10.27.27.10"`) so a future drift fix is one-line

### Phase 3 — Lint + enforcement
Add a pre-commit hook (or ruff custom rule, or a tiny `scripts/check_no_hardcoded_addrs.py`) that fails CI when an IP literal matching `10\.27\.27\.\d+` or any of the project hostnames appears outside the allowed locations (config files, test fixtures, `offices/pm/` historical docs). Wire into `make pre-commit`.

### Phase 4 — Document standing rule
Add a section to `specs/standards.md` titled "Infrastructure Addresses are Config-Driven" with the rule, the rationale (drift cost), and a code example.

## Open grooming questions

1. **Hostname vs IP preference**: when DNS for `chi-eclipse-01` and `chi-srv-01` is set up, do we prefer hostname-as-canonical with IP-as-override? Currently we use IPs everywhere because DNS isn't configured (Session 21 explicit decision). Decide whether the config field is `host` (accepts either) or `ip` + `hostname` (split).
2. **Bash consumer pattern**: bash scripts can't use Python config-loading easily. Three options: (a) a tiny `deploy/load_config_addr.sh` helper, (b) emit a `deploy/.env.addresses` file from config.json on `--init`, (c) source `~/.ssh/config` for hostnames since key-based SSH already works through aliases. Recommend (c) because it dovetails with the existing SSH workflow.
3. **Infrastructure section shape**: flat keys (`infrastructure.serverHost`) or nested per-host (`infrastructure.server.host`)? Nested matches the existing `pi.companionService` pattern; flat is one level less to traverse.
4. **Test fixture vs prod config**: should tests source from `tests/conftest.py` constants (current proposal) or from a `tests/test_config.json` (more explicit but more files)? Recommend conftest.py because it keeps the test fixture lifecycle obvious.
5. **Migration vs greenfield**: do Phase 1+2 sweep the entire repo in one big PR (single commit, atomic, easy to revert), or per-tier (one PR for Pi, one for server, one for tests)? Recommend single PR — atomicity matters for "one source of truth" properties.

## Acceptance criteria (to be finalized when entering a sprint)

- New `config.json infrastructure` section exists with all in-scope addresses; ConfigValidator has defaults
- Zero infrastructure-IP/hostname literals in `src/`, `scripts/`, `tests/`, `deploy/` (excluding the canonical config and a single test-fixture file)
- All bash scripts that need an address use the agreed bash pattern (Q2)
- specs/standards.md contains the standing rule with example code
- Pre-commit hook (or ruff/CI check) blocks new hardcoded literals
- Existing tests still pass; manual e2e validation still passes
- `make pre-commit` runs the address-lint check

## Risks

- **Big-blast-radius rewrite**: similar to US-187's obd→obdii sweep. Mitigate by following US-187's pattern: rename atomically in one commit, verify test count is identical pre/post.
- **Bash scripts and SSH-config interaction**: if bash scripts adopt `~/.ssh/config` aliases (pattern Q2 option c), that creates an implicit dependency on the user's SSH config being set up. This is fine for CIO's machine but may break in CI. Mitigate by also supporting env var override for CI runs.
- **Test fixture drift**: if production IP changes but the test fixture doesn't get updated, tests pass but prod fails (the inverse of today's bug). Mitigate by having the test fixture file IMPORT from the same source as production where possible (e.g., `from src.common.config import getInfrastructureConfig`), so they can't diverge.

## Dependencies

- Standing rule has no hard deps; can land any sprint that has bandwidth.
- Sprint 13+ candidate. Particularly nice to have BEFORE Run-phase work since Run will introduce new addresses (BT MAC binding, dongle pairing).

## Sprint placement notes

Not for Sprint 13 unless CIO bumps priority — Sprint 13 will be the Run phase (B-037) once BT pairing + car mount are done. B-044 is a Sprint 14+ candidate, but the standing rule applies starting NOW: any new code Ralph writes uses config-driven addresses.

## Out of scope

- DNS configuration (separate decision; PM rule deferred per Session 21 "DNS not configured, use IP everywhere")
- Migration from current `pi.companionService.baseUrl` shape to a unified `infrastructure` section — that's the migration this story performs
- Historical preservation: commit messages, archived PRDs, and PM session summaries that mention `.120` are intentional historical record and stay as-is
