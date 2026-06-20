# I-037: V0.27.7 US-330 race-guard regression — `startup_log.prior_boot_clean` returns 1 unconditionally; canary masked I-036 for 11 days

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | **P0 (Safety-Critical, chain-blocking)** |
| Status       | Open (V0.27.11 candidate — proposed US-342) |
| Category     | Pi diagnostics / startup_log writer / V0.27.7 regression |
| Found In     | V0.27.7 deploy (~2026-05-12) — first canary-LIE observation in startup_log post-deploy |
| Found By     | Spool (Tuner SME) 2026-05-15 post-Drain-22 forensic |
| Related      | I-036 (the PolicyKit poweroff fail that was MASKED for 11 days by this canary regression); US-330 (Sprint 33: introduced the race-guard fix that regressed); TD-051 (orphan-cleanup unit-ordering alternative that was deferred); US-263 / US-287 (startup_log writer lineage) |
| Created      | 2026-05-15                |

## Description

Pi-side `startup_log.prior_boot_clean` was a 0/1 canary intended to record whether the prior boot ended via a recognized graceful-shutdown journal signature (`Reached target Shutdown`, `Powering off`, `systemd-shutdown`, `Halting`, etc.). Since the V0.27.7 deploy (~2026-05-12), every `startup_log` record reports `prior_boot_clean=1` regardless of whether the prior boot actually contained any shutdown signature in its journal. The canary now LIES unconditionally.

This regression was introduced by **US-330** (Sprint 33), which added a 3× retry around `journalctl --list-boots` to defend against SD-card I/O contention under V0.27.6 US-322's `orphan-cleanup.timer`. The retry path or a related code change appears to have broken the heuristic — either the retry-fallback returns the default value of `1` after exception-handling, or the shutdown-signature regex was changed/loosened in the US-330 patch to match too permissively.

## Empirical Evidence (Spool 2026-05-15 forensic)

`startup_log.prior_boot_clean` pattern over time:

| Period | prior_boot_clean values | Verdict |
|---|---|---|
| Pre-V0.27.7 (2026-05-08/09) | 0, 0, 0 | Canary HONEST — flagged hard-crashes correctly |
| Post-V0.27.7 (2026-05-12 onward) | 1, 1, 1, …, 1 (every record) | Canary LIES — unconditional 1 |

**Drain 22 smoking gun**: the prior-boot journal for Drain 22 ends mid-tick with **zero** shutdown-signature lines (no `Reached target Shutdown`, no `Powering off`, no `systemd-shutdown`, no `Halting`, no `Power-Off`). Yet the corresponding `startup_log` record shows `prior_boot_clean=1`. This is empirically a hard-crash that the canary labeled as graceful.

## Interaction with I-036 — Why This Went Undetected 11 Days

I-037 is the **enabler** of the I-036 cover-up. The PolicyKit poweroff failure (I-036) has existed since V0.24.1 deploy (2026-05-04). Every drain since then has hard-crashed. From V0.24.1 through V0.27.6, the canary would have caught it (`prior_boot_clean=0` per drain). Starting V0.27.7, the canary lies, so every drain post-V0.27.7 was automatically labeled "clean" — and Spool's IRL drill notes through Drains 18–21 all read GREEN against `prior_boot_clean=1`.

**Every "drain validated" claim post-V0.27.7 was unverified.** Spool only caught it because, in tonight's Drain 22 post-mortem, they `grep`'d the actual journal for shutdown-signature lines instead of trusting the canary column.

## Steps to Reproduce

1. On any Pi running V0.27.7 or later: cause a hard-crash (`kill -9` the eclipse-obd service mid-tick, OR pull power without polkit fix in place).
2. Reboot the Pi.
3. Query the most recent `startup_log` row: `SELECT prior_boot_clean FROM startup_log ORDER BY id DESC LIMIT 1;`.
4. Observed: `1` (canary lied — there was no shutdown signature in the prior boot's journal).
5. Expected: `0` (canary should report dirty boot).

## Expected Behavior

`prior_boot_clean=1` iff the prior boot's journal contains at least one recognized graceful-shutdown signature line (e.g. `Reached target Shutdown`, `Powering off`, `systemd-shutdown`, `Halting`). `prior_boot_clean=0` otherwise. The race-guard retry-path (US-330) MUST NOT inject a default `1` value when `journalctl --list-boots` times out — uncertainty about prior state must surface as `0` (or `NULL`), never as a false `1`.

## Actual Behavior

`prior_boot_clean=1` is returned unconditionally in every record since V0.27.7 deploy (~2026-05-12), regardless of whether the prior-boot journal contains any shutdown signature.

## Impact

- **Every drain validation since V0.27.7 was a false positive.** Drains 18, 19, 20, 21 (and any others that I-038-039… haven't surfaced yet) are now suspect.
- **Masked I-036 for 11 days** — without this regression, the PolicyKit poweroff fail would have been caught at Drain 17 (the first drain post-V0.27.7).
- **`regression_manifest.json` F-012** (startup_log feature) `lastValidated` dates from V0.27.4 era are stale — those drains relied on the canary too.
- **Tester smoke tests that assert `prior_boot_clean=1`** as a "drain validated" signal are passing on the false-positive — they need re-audit (separate inbox note to tester).
- **Chain-blocking**: V0.27 chain merge to main is BLOCKED until canary is honest AND I-036 is fixed AND Drain 23 produces a credible PASS signal.

## Likely Investigation Directions (for Ralph)

Per Spool's hypothesis-pending-diagnosis:

1. **Audit US-330 race-guard logic**: walk `_readBootList` retry path; determine whether the timeout-catch branch returns a default value of `1` instead of propagating the uncertainty (NULL or 0).
2. **Diff US-330 commit vs prior shutdown-signature regex**: confirm whether the regex was changed/loosened during the patch; if so, restore the strict matcher.
3. **Look for the canary writer location** (likely `src/pi/diagnostics/startup_log_writer.py` or similar — verify the actual filename via grep). Confirm exact code path that produces the unconditional `1`.

## Acceptance Criteria (PM-level; Ralph fills in implementation)

- [ ] Root cause documented: which exact code path in US-330 (or related) yields the unconditional `1`.
- [ ] Fix applied: `prior_boot_clean` returns `0` (or `NULL`) when no shutdown signature is found in prior-boot journal. `1` ONLY when a recognized signature is matched.
- [ ] Synthetic regression test:
  - [ ] hard-crash scenario (`kill -9` the service, reboot) → `prior_boot_clean=0`
  - [ ] graceful-poweroff scenario (real `systemctl poweroff` succeeds, reboot) → `prior_boot_clean=1`
- [ ] US-330's original race-guard intent (defend against `journalctl --list-boots` timeouts under SD-card I/O contention) is preserved — retry-path doesn't inject false-positive defaults.
- [ ] Real-world validation: Drain 23 produces a credible signal — `prior_boot_clean=0` if I-036 fix fails, `prior_boot_clean=1` if I-036 fix succeeds. (I.e. canary correctly distinguishes the two outcomes for the first time since 2026-05-12.)
- [ ] Optional (US-343 if filed): backfill audit of historical drain 10–22 `startup_log` records — re-examine journalctl boot-archive per drain, output corrected interpretation of which drains were ACTUALLY graceful vs hard-crash.

## Cross-references

- **I-036** — the PolicyKit poweroff fail this canary masked; MUST ship together in V0.27.11.
- **US-330** (Sprint 33) — the patch that introduced this regression.
- **TD-051** — orphan-cleanup unit-ordering alternative to US-330's runtime race-guard; was deferred at the time; may resurface as the cleaner fix if US-330's retry-path proves too entangled.
- **US-263 / US-287** — startup_log writer lineage.
- **F-012** (`regression_manifest.json` startup-log feature) — `lastValidated` dates need revisiting after V0.27.11 ships.
- **`offices/pm/inbox/2026-05-15-from-spool-drain22-double-p0-polkit-and-canary-regression.md`** — source note.

## Source

Spool (Tuner SME) 2026-05-15 post-Drain-22 forensic note. Empirical pre/post-V0.27.7 contrast in `startup_log.prior_boot_clean` values + Drain 22 prior-boot journal grep showing zero shutdown signature against `prior_boot_clean=1`.
