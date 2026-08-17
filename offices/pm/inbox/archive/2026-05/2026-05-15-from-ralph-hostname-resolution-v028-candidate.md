# V0.28+ Backlog Candidate — Pi Hostname Resolution Cleanup
**Date:** 2026-05-15
**From:** Ralph (Dev) — Session 201
**To:** Marcus (PM)
**Priority:** Low (housekeeping; no functional impact)

## TL;DR

CIO asked whether the Pi can be referenced by name (`chi-eclipse-01`) instead of IP (`10.27.27.28`). **Today: SSH works, but ping/HTTP/raw socket from Windows do not.** Three viable fix paths; recommend filing as a V0.28+ housekeeping story rather than ad-hoc post-sprint touch. Audit script `offices/pm/scripts/audit_historical_drain_canary.py` already flipped its `DEFAULT_PI_HOST` from `10.27.27.28` to `chi-eclipse-01` since SSH config resolves it (cosmetic; no functional change).

## What works today

- `ssh chi-eclipse-01 …` — via `~/.ssh/config` alias mapping the name to `10.27.27.28`. All SSH/rsync-based tooling can use the hostname today (including `deploy-pi.sh` if it switches from `$PI_HOST` to `$PI_HOSTNAME`).

## What doesn't work today

- `ping chi-eclipse-01` from Windows — NXDOMAIN. The home router DNS at `10.27.27.1` doesn't know the name. Windows hosts file has no entry. mDNS doesn't resolve it either.
- `chi-eclipse-01.local` — also doesn't resolve. The Pi's actual hostname is `Chi-Eclips-Tuner` (legacy from the Tuner days), avahi-daemon is `active enabled`, but Windows mDNS isn't finding either name.
- Raw HTTP / urllib / socket connections — same DNS gap as ping.

Reference: see `deploy/addresses.sh` lines 30-35 — `PI_HOST` and `PI_HOSTNAME` are already exported in parallel per B-044 SSOT discipline; the variable's there, the resolution layer isn't.

## Three fix paths

| Option | Effort | Scope | Notes |
|---|---|---|---|
| **A. Windows hosts file** | 5 min, needs admin | Per-machine | One line `10.27.27.28  chi-eclipse-01` in `C:\Windows\System32\drivers\etc\hosts`. Fragile — every dev workstation needs the entry. |
| **B. Pi hostname rename** | ~30 min + sweep | Pi-wide | `sudo hostnamectl set-hostname chi-eclipse-01` + `/etc/hosts` 127.0.1.1 update on the Pi. Avahi will then advertise `chi-eclipse-01.local`. Affects deploy artifacts, eclipse-obd.service comments, anywhere that grep'd `Chi-Eclips-Tuner` — needs a sweep. |
| **C. Router-level DNS** | 5 min, needs router admin | LAN-wide | Add an A record `chi-eclipse-01 → 10.27.27.28` on the home router. Works for every LAN client; no per-machine config. **Recommended long-term** — same approach probably applies to `chi-srv-01` for consistency. |

## My recommendation

**Option C** (router DNS) — best LAN-wide reach, lowest per-machine overhead, no Pi-side rename churn. Can be paired with **Option B** if you want the Pi's self-hostname to match the canonical name (cosmetic; B alone isn't sufficient because mDNS doesn't reach far enough). Defer Option A (hosts file) — it's a band-aid that needs reapplying to every dev box.

Filing as a single V0.28+ housekeeping story would cover: (1) router DNS A records for both `chi-eclipse-01` and `chi-srv-01`, (2) optional Pi hostname rename + sweep of `Chi-Eclips-Tuner` references in deploy artifacts, (3) sweep all `$PI_HOST` / `$SERVER_HOST` consumers and convert SSH-friendly ones to `$PI_HOSTNAME` / `$SERVER_HOSTNAME` (no-op functionally but readability win).

Not chain-blocking, not V0.27.11-related — just clean cosmetics.

— Ralph (Session 201)
