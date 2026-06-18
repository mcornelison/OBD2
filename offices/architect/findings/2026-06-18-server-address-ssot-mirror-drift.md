# Finding — server-address SSOT is "documented duplication," and mirror-drift is unguarded

**Date**: 2026-06-18
**Author**: Atlas (Architect)
**Severity**: Med (the immediate breakage is fixed; the structural gap remains)
**Trigger**: CIO moved chi-srv-01 from `10.27.27.10` → `10.27.27.120`. Several sites still held
`.10`; the Pi's sync/Ollama/update paths were pointing at a dead address (verified: `.120`
replies ~5 ms, `.10` destination-unreachable). Fixed in commit `7373f55` (dev).

## What the fix did
Updated every functional + canonical `.10` site to `.120`: `config.json` (×3:
`server.network.serverHost`, `serverBaseUrl`, `companionService.baseUrl`), `validator.py`
DEFAULTS, `deploy/addresses.sh`, `.env.production.example`, the coupled tests, and stale
docstrings. Verified green (config-validator 47/47, migration tests 53/53, zero `.10` literals
repo-wide outside `.md`).

## Root cause — the SSOT was never single
The server address is held as a **literal in (at least) three sanctioned places that must move
together**:
1. `config.json server.network.*` + `pi.companionService.baseUrl` — the declared canonical source.
2. `src/common/config/validator.py` DEFAULTS registry — `# b044-exempt: mirrors config.json`.
3. `deploy/addresses.sh` — `# b044-exempt: canonical bash-side mirror of config.json`.
   (plus `.env*.example`, and several test fixtures that pin the literal.)

The B-044 audit (`scripts/audit_config_literals.py`) **exempts all three** (and `tests/`, and
docs). So the audit guarantees *no new hardcoded literal appears in non-exempt runtime source* —
but it does **nothing** to verify the sanctioned mirrors still **agree with each other**. The
failure mode that actually bit us — change config.json, forget the validator default and
`addresses.sh` — is precisely the one the audit cannot see. This is "documented duplication,"
not single-source-of-truth.

Compounding it: **`config.json` itself triplicates the address** — `companionService.baseUrl`,
`server.network.serverBaseUrl`, and `server.network.serverHost` all encode the same server, so
even the canonical file has three copies that must be kept consistent by hand.

## Recommendations (architectural, not yet built)
1. **Add a mirror-consistency check** (cheap, high value): a test/lint that parses `config.json`,
   `validator.py` DEFAULTS, and `deploy/addresses.sh` and asserts the server/Pi addresses match.
   Turns "remember to update all three" into a gate. This closes the exact hole that caused this.
2. **De-duplicate within `config.json`**: derive `companionService.baseUrl` from
   `server.network.serverBaseUrl` (or from `serverHost`+`serverPort`) in the consumer, so the
   literal lives in exactly one config key.
3. **Strategic option — hostname-based resolution.** The real SSOT is to reference the *name*
   `chi-srv-01` (resolved via LAN DNS / `/etc/hosts`) instead of an IP anywhere. Then relocating
   the box is a one-line DNS/hosts change with **zero** repo edits. Caveats: depends on reliable
   LAN name resolution, and sync's offline-probe (`hasRouteToServer`) is IP-route-based today, so
   this is a design change with its own failure modes — flag for grooming, not a hotfix.
4. **Pre-existing B-044 finding** (out of scope for the IP move, noted for completeness): a
   hardcoded hostname in a *log string* at
   `src/pi/power/power_watch/tasks/sync_with_server.py:82` keeps the audit non-clean. It's a log
   message, not a runtime address — either pull the hostname from config or add a one-line
   `# b044-exempt:` pragma with a reason.

## Connection to the SSOT-bus / EDR work (A-14)
This is the same disease the SSOT-bus direction targets, one tier up: a value duplicated across
N sites that drift. The cure is identical in spirit — one canonical source, everything else
*derives* or *references*, and a gate that fails when a copy diverges. Worth citing as a concrete
motivating example when that epic grooms.

— Atlas

---

## Resolution (2026-06-18, same day)

**Recommendation #1 (mirror-consistency gate) — BUILT.** TDD, 9 tests, ruff clean:
- `scripts/audit_address_mirrors.py` — parses all three mirrors + intra-config coherence,
  returns `MirrorMismatch` list; CLI + importable. Stdlib-only (matches the B-044 audit posture).
- `tests/lint/test_address_mirror_consistency.py` — pure-core synthetic-divergence tests
  (proves the mechanism catches the exact .10/.120 drift) + a standing gate over the real repo.
- Runs automatically inside `pytest tests/lint/`. This closes the precise hole that caused the
  breakage: B-044 now catches *new stray literals*, A-15 catches *the sanctioned copies drifting*.

**Recommendation #4 (B-044 log-string) — FIXED.** `# b044-exempt` pragma added at
`sync_with_server.py:82`; `python scripts/audit_config_literals.py` → 0 findings (was 1).

**Recommendation #2 (config.json de-dup) — ROUTED** to Ralph as a gap:
`offices/architect/gaps/2026-06-18-config-json-server-address-dedup.md` (runtime consumer change).

**Recommendation #3 (hostname-based resolution) — ROUTED** to PM as a design-Story candidate
(needs Atlas+CIO; sync offline-probe caveat). PM note:
`offices/pm/inbox/2026-06-18-from-atlas-a15-mirror-lint-built-and-followups.md`.

A-15 downgraded on the Watch List: the immediate breakage was fixed (`7373f55`) and the
structural gate now exists; remaining items (#2 de-dup, #3 hostname) are groom-tracked, not open
architectural risk.

— Atlas
