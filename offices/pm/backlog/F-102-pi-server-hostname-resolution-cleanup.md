---
id: F-102
parent: E-004
status: pending
renamedFrom: B-102
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-102: Pi + server hostname resolution cleanup (`chi-eclipse-01` / `chi-srv-01` LAN-wide)

| Field        | Value         |
|--------------|---------------|
| Priority     | Low (housekeeping; no functional impact — SSH/rsync tooling already works via `~/.ssh/config` alias) |
| Status       | Pending (V0.28+ candidate) |
| Category     | infrastructure / networking / housekeeping |
| Size         | S (router DNS = 5 min; optional Pi rename + reference sweep adds ~30 min) |
| Related PRD  | None |
| Dependencies | B-044 (config-driven addresses SSOT — `PI_HOST`/`PI_HOSTNAME` already exported in parallel in `deploy/addresses.sh`; this closes the resolution-layer gap behind the existing variable). Also closes the long-standing `Chi-Eclips-Tuner` hostname-drift owed-bookkeeping item. |
| Created      | 2026-05-15    |

## Description

CIO asked whether the Pi can be referenced by name (`chi-eclipse-01`) instead of IP (`10.27.27.28`). Today: **SSH/rsync work** (via `~/.ssh/config` alias → `10.27.27.28`), but **ping / raw HTTP / urllib / socket from Windows do NOT** — the home router DNS (`10.27.27.1`) doesn't know the name, Windows hosts file has no entry, mDNS doesn't resolve `chi-eclipse-01` or `chi-eclipse-01.local`. The Pi's actual hostname is still the legacy `Chi-Eclips-Tuner` (the rename documented as applied in Sprint 14 US-176 was never actually effective — this is the recurring owed-bookkeeping drift item). The cosmetic symptom is the `sudo: unable to resolve host chi-eclipse-01` warning spam during `deploy-pi.sh` (deploy succeeds anyway).

## Three fix paths (Ralph's analysis)

| Option | Effort | Scope | Notes |
|---|---|---|---|
| A. Windows hosts file | 5 min, admin | Per-machine | `10.27.27.28 chi-eclipse-01` line. Fragile — every dev box needs it. Band-aid. |
| B. Pi hostname rename | ~30 min + sweep | Pi-wide | `hostnamectl set-hostname chi-eclipse-01` + Pi `/etc/hosts` 127.0.1.1 update; avahi then advertises `.local`. Needs a sweep of `Chi-Eclips-Tuner` refs in deploy artifacts + service comments. Fixes the sudo warning spam. |
| C. Router DNS A record | 5 min, router admin | LAN-wide | A record `chi-eclipse-01 → 10.27.27.28` (+ `chi-srv-01` for consistency). Works for every LAN client, no per-machine config. **Ralph + PM recommend long-term.** |

## Acceptance Criteria

- [ ] `chi-eclipse-01` (and `chi-srv-01`) resolve LAN-wide from Windows for ping / HTTP / socket — not just SSH (Option C)
- [ ] (Optional, pairs with C) Pi self-hostname = `chi-eclipse-01`; `Chi-Eclips-Tuner` references swept from deploy artifacts + service comments; sudo host-resolution warning gone from `deploy-pi.sh`
- [ ] (Optional readability) SSH-friendly `$PI_HOST`/`$SERVER_HOST` consumers converted to `$PI_HOSTNAME`/`$SERVER_HOSTNAME` (functional no-op per B-044 SSOT)
- [ ] No regression in existing SSH/rsync/deploy tooling

## Validation Script Requirements

- **Input**: `ping chi-eclipse-01`, `curl http://chi-eclipse-01:<port>/...`, `ssh chi-eclipse-01` from a Windows dev box
- **Expected Output**: all three resolve + connect (today only `ssh` works)
- **Database State**: N/A (infrastructure)
- **Test Program**: a small connectivity check script asserting name resolution for both hosts across ping/HTTP/SSH

## Notes

- Ralph note: `offices/pm/inbox/2026-05-15-from-ralph-hostname-resolution-v028-candidate.md` (2026-05-15)
- Ralph recommends Option C (router DNS), optionally paired with B (Pi self-hostname match — cosmetic; B alone insufficient because mDNS doesn't reach far enough). Defer Option A.
- Ralph already flipped `audit_historical_drain_canary.py` `DEFAULT_PI_HOST` `10.27.27.28`→`chi-eclipse-01` (SSH-config resolves it; cosmetic, no functional change).
- This **subsumes the long-standing `Chi-Eclips-Tuner` rename-drift** owed-bookkeeping item — close that audit-trail note when B-102 is groomed/scheduled (no separate TD needed).
- Not chain-blocking, not V0.27.11-related — pure cosmetics. Reference `deploy/addresses.sh` lines 30-35.

## Source

Ralph Session 201 (2026-05-15), prompted by CIO question during the V0.27.11 co-pilot session.
