# CIO ratified: closeout-commit path + Sprint 40 scope expansion incoming

**From**: Marcus (PM)
**To**: Ralph / Rex
**Date**: 2026-05-21

---

## TL;DR

CIO ratified the two open decisions from BL-020 / PM ack:

1. **Commit handshake**: option (a) — re-launch Ralph for one closeout iteration. Standard pattern.
2. **Scope**: Tester's I-040 (V0.27.7 false-pass cluster) joins Sprint 40 as **US-348 + US-349**. Sprint expands 4 → 6 stories.

## What you do on re-launch

When CIO drives `ralph.sh N`:

1. **Closeout-commit** your existing T1+T2+T3 work:
   - `src/pi/power/power_watch/__main__.py` (US-344 F-7 fix)
   - `tests/pi/power/power_watch/test_boot_grace_latch.py` (US-344 test)
   - `deploy/boot-progress-finalize.service` (US-345 F-8 fix)
   - `tests/deploy/test_boot_progress_finalize_service.py` (US-345 test)
   - `specs/architecture.md` (US-346 §10.6 amendment — pending Atlas gate)
   - `offices/ralph/sprint.json` (status updates US-344..US-346 `passes:true`)
   - `offices/pm/blockers/BL-020.md`
   - `offices/ralph/progress.txt` + `offices/ralph/ralph_agents.json`
   Group as you see fit (one commit or per-story; your call). All on `sprint/sprint40-bugfixes-V0.27.16`.

2. **Re-emit `HUMAN_INTERVENTION_REQUIRED`** cleanly after the closeout commits, per the headless contract. ralph.sh stops.

3. **Hold the floor**. PM will expand sprint.json with US-348 + US-349 in a follow-up commit after yours lands. You don't draft these stories — PM owns the story authoring per role boundary. Expect a PM commit message like `feat(pm): Sprint 40 scope expansion -- US-348 + US-349 (I-040 V0.27.7 false-pass redo)` on top of yours.

4. **Next re-launch after PM scope expansion**: pick US-348 + US-349 in dependency order. They're independent of T1/T2/T3 and of each other.

## What US-348 + US-349 will say (preview, so you're not surprised)

- **US-348 — US-326-redo**: drive_summary server analytics writer (start_time / end_time / duration_seconds / row_count / is_real) actually fires on every Pi-sync drive_end round-trip. Acceptance: real-drive IRL round-trip + post-sync DB read-back showing those 5 fields populated and arithmetically consistent with realtime_data. NOT a synthetic test where a mocked seam returns success. Per Tester's `feedback-tester-validate-deploy-fixes-irl-not-just-code` discipline.
- **US-349 — US-328-redo**: drive_statistics Pi-side writer (per-parameter min/max/avg/std_dev + outlier bounds) actually fires on drive_end. Acceptance: real-drive IRL round-trip + Pi-side DB read-back showing ≥1 row per parameter present in the drive's realtime_data, with sensible min/max/avg. Same discipline.

Both will be size S or M depending on the diagnostic dig — the writer code exists per the V0.27.7 stories' filesActuallyTouched; figuring out why it doesn't fire on a real drive_end is the work.

## Drill timing per CIO

In-car drill (US-347) runs **ASAP after deploy**. Sequence:

1. You closeout-commit (this iteration)
2. PM scope expansion commit (US-348 + US-349 added)
3. You ship US-348 + US-349 (next iterations)
4. PM `/sprint-deploy-pm` (V0.27.16 to Pi + server)
5. CIO drives in-car drill: F-7 reproduction (Test 2 engine crank within boot-grace) + F-8 verification (first-boot CLEAN_COMPLETE) + US-348/349 fix-validation drive
6. Atlas gates verdict
7. Tester `/sprint-validated`
8. PM `/chain-validated`

Atlas pre-registers the full drill procedure when deploy lands (mirrors Sprint 39 §9 cadence).

## Other state

- **B-102 hostname**: Tester observed Pi reports `Chi-Eclips-01` since 09:49 yesterday. PM will verify + close B-102.
- **Two lint failures from V0.27.15** (B-044 chi-srv-01 string + ralph promise-tag drift) — fold into your closeout commits if convenient, or file TD-054 to defer.
- **Atlas US-346 §10.6 amendment gate** — your ask is in his inbox; Atlas signs off independent of the rest.

— Marcus
