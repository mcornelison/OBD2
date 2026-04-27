# US-230 closure — journald persistence deploy hardening

**Date:** 2026-04-23
**From:** Rex (Ralph, Session 101, Agent 1)
**To:** Spool
**Story:** US-230 (Sprint 18)
**Closes:** Your `offices/pm/inbox/2026-04-23-from-spool-post-deploy-system-test-findings.md` Section 2 ("Persistent journald drop-in installed but NOT effective")

## TL;DR

- `step_install_journald_persistent` now verifies `/var/log/journal/<machine-id>/` + `journalctl --disk-usage > 0` instead of just "parent dir exists" (your exact failure mode).
- On failure the step prints the 5 US-230 AC #3 diagnostics and exits non-zero without silently mkdir'ing anything.
- New pytest+bash test `tests/deploy/test_journald_persistent_install.{sh,py}` re-runs the same four assertions independent of a deploy; auto-skips (exit 77) on CI runners without Pi SSH.
- **Current Pi state is healthy** (self-healed since your audit); the fix is forward-looking deploy hardening.

## Current state finding (evidence your 2026-04-23 audit observed a transient failure)

SSH probe of `10.27.27.28` at Session 101 closeout:

```
machine-id:              2e626dcc3a714fc2a258860b0642db98
/var/log/journal/<id>/:  created 2026-04-23 13:34 (today), 24M
journalctl --disk-usage: 24M in the file system
journalctl --verify:     PASS on system.journal + user-1000.journal
systemctl is-active:     active
earliest persistent entry: 2026-04-23T13:34:52-05:00 (kernel boot line)
```

Interpretation: between your audit earlier today and my Session 101 probe, the Pi rebooted at 13:34 and systemd-journald correctly created the machine-id subdir on that boot. The drop-in was always installed correctly; the failure mode was purely "drop-in present but journald never restarted to pick up Storage=persistent." US-230's enforcement closes that gap — a future deploy that installs a new drop-in without triggering the restart now fails loudly at the post-check instead of leaving the Pi in your observed state.

The `earliest persistent entry` line shows hostname `Chi-Eclips-Tuner` (legacy, pre-`chi-eclipse-01`-rename per MEMORY.md); not my story's scope, but worth flagging to Marcus as an open item on the hostname rename reboot-persistence question.

## Fix shape (per AC)

### Pre-flight audit (AC #1)
Completed. `/var/log/journal/` state probed via SSH before any code change (healthy now, 24M of logs). Drop-in `/etc/systemd/journald.conf.d/99-obd-persistent.conf` content verified as canonical Storage=persistent. systemd-journald active.

### Strengthened post-check (AC #2 + AC #3)
`deploy/deploy-pi.sh::step_install_journald_persistent` now:

1. Reads `/etc/machine-id` on the Pi; fails with exit 7 if empty.
2. Verifies `/var/log/journal/<machine-id>/` is a directory (not just `/var/log/journal/`).
3. Parses `journalctl --disk-usage` and verifies the output matches the positive regex `take up [1-9][0-9.]*[BKMGT]? in` — rejects `0B`, accepts `24M` / `1.5G` / `100K` / `1B`.
4. Retries the disk-usage check once after a 3s sleep so a just-restarted journald doesn't false-negative on a stale cache.
5. Sleeps 2s after any actual restart (only when the drop-in content changed) so journald has time to create the subdir + rotate the first log segment.
6. On failure emits the 5 AC #3 diagnostics (`journalctl --disk-usage`, `ls -la /var/log/journal/`, `journalctl --verify` head 20, conf.d contents, `systemctl is-active systemd-journald`), then exits 7.
7. Honors invariant #2: no `mkdir /var/log/journal/<machine-id>/` as silent recovery.

The post-check runs unconditionally every deploy — even when the drop-in was cache-hit-unchanged — because your exact failure mode was "already-installed drop-in on an empty /var/log/journal." A skip-when-unchanged post-check would have missed that.

### Idempotent + first-run graceful (AC #5 + stopCondition #1)
Re-running on a healthy Pi is a no-op that still verifies. A first-run deploy where the machine-id subdir doesn't yet exist works because:
1. The `cmp -s` branch installs + restarts, triggering the 2s post-restart sleep.
2. systemd-journald creates `/var/log/journal/<machine-id>/` on that restart since Storage=persistent is set.
3. The post-check finds the subdir after the sleep.

If the first-run case ever fires the failure path (subdir still missing after 2s), the diagnostic output surfaces the root cause rather than papering it over.

### Test coverage (AC #4 + AC #6)
- `tests/deploy/test_journald_persistent_install.sh` (new, 4 assertions) — runs on a machine with SSH to the Pi; exits 77 (autotools SKIP) when SSH is unreachable so CI without Pi access doesn't red-flag.
- `tests/deploy/test_journald_persistent_install.py` (new, 1 test) — pytest wrapper with SKIP semantics preserved through `pytest.skip()`.
- Existing `tests/deploy/test_journald_persistent.py` still covers static content of the drop-in itself (Storage=persistent locked, forbidden modes guarded).
- Existing `tests/deploy/test_deploy_pi.sh` smoke test still passes 29/29 after the enhancement (the `--dry-run` preview branch doesn't invoke the remote post-check).

### Specs + docs (AC #6)
- `specs/architecture.md` Section 8 (Logging and Observability) — new "Persistent Journald (US-210, US-230 acceptance signal)" subsection with the 4-row signal table + failure-mode policy.
- `docs/testing.md` — new "Verifying persistent journald after deploy" section (4 subsections: via deploy script / via bash test / SSH spot-check / off-Pi pytest wrapper).
- Modification History entry in docs/testing.md.

**Scope-fence honorarium (per refusal rule #3).** US-230's `filesToTouch` said "specs/architecture.md Section 10 (journald persistence: document that Storage=persistent requires systemd-journald restart AND that /var/log/journal/<machine-id> being non-empty is the acceptance signal)". Section 10 in architecture.md is "Display Architecture" which isn't the right semantic home for journald acceptance. I placed the new subsection in Section 8 (Logging and Observability) which IS the semantic home. Flagging for Marcus to adjudicate if the scope-fence intent was literal-section-10 vs topically-correct.

## Verification run (US-230 AC #7)

```text
bash tests/deploy/test_deploy_pi.sh            -> 29 passed / 0 failed
bash -n deploy/deploy-pi.sh                    -> OK
bash deploy/deploy-pi.sh --dry-run | grep US-230 -> shows the new verify line
pytest tests/deploy/test_journald_persistent_install.py -v -> PASSED (SSH to Pi ran live; all 4 assertions green)
ruff check tests/deploy/test_journald_persistent_install.py -> All checks passed!
python offices/pm/scripts/sprint_lint.py       -> 0 errors / 23 warnings (all pre-existing Sprint 18 sizing informationals)
pytest tests/ -m "not slow" -q                 -> 3264 passed / 17 skipped / 19 deselected / 0 regressions / 2 pre-existing warnings in 863.76s (14:23); exact +1 vs US-229 baseline 3263
```

Shellcheck not installed on the Windows dev workstation, so the deploy-pi.sh change was verified with `bash -n` (syntax) + the full smoke test. No shell-specific warnings expected — the change reuses the existing remote-heredoc idiom for sudo/journalctl plumbing.

## What I did NOT do (scope honored)

- Did NOT touch `deploy/journald-persistent.conf` — drop-in content stays Storage=persistent per invariant #4 + doNotTouch list.
- Did NOT touch `deploy/eclipse-obd.service` (unrelated, also on doNotTouch).
- Did NOT touch other deploy-pi.sh steps (rfcomm-bind, pip install, etc).
- Did NOT mkdir `/var/log/journal/<machine-id>/` on the Pi even though it exists — current state is already healthy, no recovery needed.
- Did NOT address the legacy `Chi-Eclips-Tuner` hostname observed in journal entries — out of story scope, flagged above for Marcus follow-up.

## Open item for Marcus

Section-placement scope-fence judgment call (Section 8 vs Section 10) noted above. If Marcus wants the subsection moved to literal Section 10 per grooming text, one-line edit — say the word.

— Rex (Agent 1)
