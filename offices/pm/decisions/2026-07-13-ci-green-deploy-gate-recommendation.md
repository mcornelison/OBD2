# Recommendation: CI-green deploy-gate (make the migration-drift check actually gate production)

**From:** Marcus (PM) · **Date:** 2026-07-13 · **Decision owner:** CIO
**Resolves:** BL-022 (US-470 CI-enablement) + Atlas's V0.29.12 coherence note · **Refs:** US-464, US-469, US-470, TD-055, US-186, BL-019/020/021

## The problem in one paragraph

BL-019 → BL-020 → BL-021 were three consecutive migration bugs that were **green on SQLite/`create_all` but wrong on real MariaDB** — caught only *at* deploy (production blocked, safely, three times). US-464 built a real-MariaDB migration-chain test that catches the class; US-470 built the CI workflow to run it (`migration-drift.yml`, MariaDB 11.8 service container). **But that check doesn't gate deploys today**, because: (a) the test needs Docker, the PM's Windows deploy bench has none; (b) GitHub Actions is disabled (US-186 removed `pylint.yml` for email-flood noise); and (c) `/sprint-deploy-pm` deploys from `dev` with **no CI-green precondition**. So the gate that would catch the next BL-02x pre-deploy currently catches nothing pre-deploy.

**Not an emergency:** the deploy runs migrations against real prod MariaDB and fails *loudly + safely* on drift (aborts before the version switch — that's how BL-020/021 surfaced). This recommendation is about making the check **proactive** (catch before the deploy attempt) instead of **reactive** (discover mid-deploy).

## Three coupled decisions

### 1. Enable GitHub Actions? — **Recommend YES.**
- The US-186 removal was specifically about `pylint.yml` emailing a failure on **every push**. Ralph's `migration-drift.yml` is deliberately narrow: `pull_request → dev/main` + path filter (migrations/tests only) + `workflow_dispatch` — **never blanket `on: push`**. It won't reproduce the flood.
- One-time notification tune: GitHub → Settings → Notifications → Actions → notify on failure only (or rely on the Actions tab).
- Cost: trivial for a solo repo — the MariaDB-service job runs only on migration-touching PRs, a few minutes each; well within the free tier.
- **Payoff:** one green run flips US-470 `passes:true` and **closes TD-055** — the durable guard against the entire BL-02x class.

### 2. How to make the deploy require CI-green?
The gap: CI triggers on `pull_request → dev`, but `/sprint-deploy-pm` merges sprint→dev **directly** (`--no-ff`), not via PR — so CI may never run on the integration commit, and the deploy (from `dev`) sees no CI signal.

- **Option A (recommended) — PR-based sprint integration.** Change `/sprint-deploy-pm` Phase 3.5 to push the sprint branch and open a PR into `dev` (`gh pr create`); CI runs on the PR; merge only when green. Then deploy-from-`dev` is CI-green **by construction**. *Pro:* CI-native, structural gate, adds a review surface. *Con:* one extra PR step in the merge flow.
- **Option B — post-merge CI + deploy-time poll.** Add a narrow `push: [dev]` trigger (path-filtered) to `migration-drift.yml`, and a `/sprint-deploy-pm` pre-deploy gate that uses `gh run list --workflow=migration-drift.yml --branch=dev`, finds the run for `git rev-parse dev`, and **HALTs unless `conclusion=success`**. *Pro:* keeps the direct-merge flow. *Con:* deploy waits/polls for the post-merge run; more moving parts.

Either way the deploy **verifies CI actually ran + passed for the exact SHA** (run-not-trust — same principle as US-469's local gate), never "we think it's green." This composes with US-469: local `not-slow` gate for fast feedback, CI/PR gate for the Docker-requiring real-MariaDB drift check.

**`gh` CLI is available (v2.86.0)**, so both options are implementable.

### 3. Interim until Actions is enabled — DSN-manual gate.
Run the live layer on demand against a real MariaDB 11.x as part of the deploy gate:
`OBD2_MARIADB_TEST_DSN=mysql+pymysql://user:pass@host:3306/db pytest tests/server/test_migration_chain_real_mariadb.py -m integration`
(point it at chi-srv-01's MariaDB or a throwaway 11.x — the same drift the deploy proves, on demand). TD-055 stays **OPEN-downgraded** (honest) until CI actually gates.

## What I recommend, concretely

1. **Enable Actions** (your policy call, reverses US-186) + tune notifications.
2. **Choose Option A** (PR-based integration) — cleaner, structural.
3. I then: push the `migration-drift.yml` branch, open the first PR to prove one green run → **close BL-022 / flip US-470 / close TD-055**; and groom the small `/sprint-deploy-pm` PR-integration change (an S story for Ralph, or a PM-tooling edit).

## Effort / risk
- Enabling Actions + first green run: **minutes** (you enable in repo settings; I push + open the PR). Artifacts (workflow, `requirements-dev.txt`) already exist.
- `/sprint-deploy-pm` change: **small** (~S).
- Risk: low. Worst case the container job flakes → we fall back to the DSN-manual interim (#3), which is already in place.

## Open question for you
Do you want CI to gate **only migration-touching changes** (path-filtered, my recommendation — minimal noise) or **the full `not-slow` suite on every PR to dev** (broader safety net, closer to "real CI", slightly more runs)? The migration-drift job is the BL-02x-specific gate; a broader suite is a separate, larger decision.
