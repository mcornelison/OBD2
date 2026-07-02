# US-435 hostname sweep — done, + one naming decision for the CIO

**From:** Ralph (Rex, Dev) · **To:** Marcus (PM) / CIO · **Date:** 2026-07-02 · **Re:** US-435 / F-102

US-435 is `passes: true` (committed to the sprint branch). Summary + the one thing worth a human glance below.

## What shipped (code/config/docs sweep)

- `deploy/deploy-pi.sh` `step_set_hostname`: **added `chi-eclips-01` to the acceptable-pre-rename whitelist.** Rename target is unchanged (`$PI_HOSTNAME` = `chi-eclipse-01`). Additive only — no existing branch altered.
- `.env.production.example` + `src/pi/README.md`: stale `chi-eclipse-tuner` → canonical `chi-eclipse-01` (comment/doc only).
- Left intentionally: the `deploy-pi.sh` whitelist keeps `chi-eclipse-tuner`/`chi-eclips-tuner` (a still-legacy Pi must remain renamable); `scripts/audit_config_literals.py` keeps `chi-eclipse-tuner` in its *detection* set (flags anyone re-hardcoding the legacy name); historical design specs under `docs/superpowers/**` left as dated snapshots (they document the old→new transition table).

Gates: `bash -n` OK; `tests/deploy/test_deploy_pi.{py,sh}` + `tests/lint/test_address_mirror_consistency.py` all green (deploy-pi `--dry-run --init` offline-safe = the DoD dry-run criterion). No `.py` changed → ruff N/A.

## The decision (why this note, not a silent close)

Live read-only query of the Pi (`ssh mcornelison@10.27.27.28 hostname`) returned **`Chi-Eclips-01`** — dropped the "e". Every piece of tooling (SSH `~/.ssh/config` alias, `deploy/addresses.sh` `PI_HOSTNAME`/`PI_DEVICE_ID`, `config.json` `piHostname`/`piDeviceId`, the A-15 mirror lint) uses **`chi-eclipse-01`** (with "e"). `/etc/hosts` 127.0.1.1 = `Chi-Eclips-01 Chi-Eclips-Tuner`.

SSH/deploy still work (the alias resolves by IP, not OS hostname), and `device_id` comes from config (not `hostname`), so **data identity is unaffected**. The only path keyed on the real OS hostname was `step_set_hostname`, which would have hit its `*)` refuse branch (exit 6) on a fresh `--init` — now fixed.

**CIO picks the convergence trigger** (both land the Pi at the canonical `chi-eclipse-01`):
- **A (automatic):** next `deploy-pi.sh --init` renames `Chi-Eclips-01` → `chi-eclipse-01` and rewrites `/etc/hosts` (my whitelist change enables this).
- **B (manual, 5s):** `ssh chi-eclipse-01 'sudo hostnamectl set-hostname chi-eclipse-01'` + fix the 127.0.1.1 line.

Either kills the residual `sudo: unable to resolve host` warning. I did **not** run a live rename (live-Pi mutation = ops/PM, not a Ralph in-sprint action).

## Still human-ops (F-102 Option C, outside the repo)

LAN-wide name resolution (ping/HTTP/socket by name from Windows, not just SSH) needs the **router DNS A record** `chi-eclipse-01 → 10.27.27.28` — F-102's recommended long-term fix. Nothing in the repo can do that; flagging so it isn't lost.
