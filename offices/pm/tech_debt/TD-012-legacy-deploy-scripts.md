# TD-012 — Legacy `scripts/deploy*.sh` overlap with new `deploy/deploy-pi.sh`

**Filed:** 2026-04-17 by Rex (Ralph Agent), during Sprint 10 / US-176

## Problem

`scripts/deploy.sh`, `scripts/pi_setup.sh`, and `scripts/deploy-env.sh` are
the previous-generation Pi deploy tooling (Rex, Sessions ~Jan 2026). With
US-176 (Sprint 10 Crawl phase) we now ship `deploy/deploy-pi.sh` as the
canonical Pi deploy path that mirrors `deploy/deploy-server.sh`'s shape.

The two implementations overlap and will diverge:

| Old (legacy)              | New (US-176)              |
|---------------------------|---------------------------|
| `scripts/deploy.sh`       | `deploy/deploy-pi.sh`     |
| `scripts/pi_setup.sh`     | `deploy/deploy-pi.sh --init` |
| `scripts/deploy-env.sh`   | (intentionally left out — env is operator-managed) |

The Makefile's `deploy`, `deploy-first`, `deploy-status`, `deploy-env`
targets all point at the legacy `scripts/*` files, so `make deploy` invokes
the OLD script. Operators reading the new README will get a different
deploy than `make deploy` actually runs.

## Why not fix in US-176

Per CIO rule "strict story focus — never fix adjacent code issues":
- `Makefile` and `scripts/deploy*.sh` are NOT in US-176's filesToTouch list
- US-179 (systemd service deployment) explicitly DOES list `Makefile` in
  its filesToTouch — it is the natural place to update the Makefile's
  deploy target wiring, and to either retire or repoint the legacy
  scripts entirely
- Doing it here would muddy the US-176 commit and make code review harder

## Suggested resolution (carry into US-179 or a small housekeeping pass)

1. Update Makefile:
   - `deploy:` → `bash deploy/deploy-pi.sh`
   - `deploy-first:` → `bash deploy/deploy-pi.sh --init`
   - `deploy-status:` → keep as is (it's just `systemctl status`); or
     replace with `bash deploy/deploy-pi.sh --restart` + status line
   - `deploy-env:` → either keep (env push is a separate concern) or drop
2. Decide one of:
   a. **Delete** `scripts/deploy.sh`, `scripts/pi_setup.sh`,
      `scripts/deploy-env.sh` (cleanest — the new script subsumes them)
   b. **Move** them under `scripts/legacy/` with a README pointer
   c. **Rewrite** them as thin shims that call `deploy/deploy-pi.sh`

My recommendation: option (a). The old scripts were written before the
sprint-contract / spec discipline matured, and the new script captures the
operator workflow correctly. Keep `scripts/` for things that aren't
deployment (e.g. `scripts/report.py`, `scripts/seed_scenarios.py`).

## References

- New script: `deploy/deploy-pi.sh`
- New tests: `tests/deploy/test_deploy_pi.sh`, `tests/deploy/test_deploy_pi.py`
- Sprint contract: `offices/ralph/sprint.json` US-176 (filesToTouch
  intentionally excludes `Makefile`)
- Sprint contract: `offices/ralph/sprint.json` US-179 (filesToTouch DOES
  include `Makefile`)

## Severity

Low. The legacy script still works against the Pi if invoked directly. The
risk is operator confusion ("which script do I run?") and slow drift as
new conventions land in only one of the two implementations.
