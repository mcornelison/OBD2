---
name: tester-validates-deploy-fix-stories-irl-not-just-that-the-code-landed
description: "When validating a deploy-fix / wire-up story, distinguish (a) \"fix code is deployed\" from (b) \"fix code triggers in practice\" — they're not the same. Always exercise the IRL invocation path the fix targets."
metadata:
  node_type: memory
  type: feedback
  scope: tester-local
  migratedFrom: ~/.claude/projects/Z--o-OBD2v2/memory/feedback_tester_validate_deploy_fixes_irl_not_just_code.md
  migratedOn: 2026-05-20
  migrationReason: "CIO memory-boundary directive 2026-05-20: agent-personal knowledge lives in offices/<agent>/knowledge/, not shared memory."
---

When a story claims to FIX a class of failure (path-mangle, self-loop ssh, race, etc.), the validation gate must execute the failure path post-fix, not just verify the fix code is present in the deployed file.

**Why:** US-331 (V0.27.8) shipped passes:true with a synthetic regression test (`tests/scripts/test_backfill_deploy_contexts.py`) that mocked the MSYS guard at the Python level. The synthetic test passed; the deploy-and-invoke gate FAILED with the byte-identical MSYS path-mangle error from V0.27.7. The fix code (`_buildSubprocessEnv`, `_isLocalServer`, `_readDatabaseUrlFromEnv`, `localServerCheck`) was all present in the deployed script — it just didn't catch the case in practice because the path-translation happens at the MSYS2 argv-translation layer **before the Python process launches**, which a Python-level mock cannot reproduce. PM filed I-032; V0.27.9 / US-337 redoes it. Tester independently confirmed via `--count-stranded` on chi-srv-01 — still throws `Host key verification failed` (the Context 2 self-loop ssh path).

**How to apply:** For any "fix X bug" story, validation must include:

1. **Confirm code is deployed** — grep the deployed file for the new helpers/branches/guards. (Necessary but not sufficient.)
2. **Reproduce the original failure path** — find the exact invocation that triggered the bug pre-fix; run it post-fix; require success.
3. **Match the failure context** — Git-Bash subprocess vs. PowerShell vs. cmd.exe vs. self-ssh-loop vs. cold-boot-under-IO-contention. The context is part of the bug; substituting a friendlier context invalidates the gate.
4. **For shell-to-subprocess bugs specifically**: synthetic unit tests that mock at the Python boundary cannot prove a fix for path-translation that happens at the shell→binary boundary. Reject `passes:true` if the verification only ran Python-mocked tests for a shell-level bug. Require a real-subprocess (or live remote) execution in the validation list.

**Cross-references / anchor case set (the pattern has now happened 5+ times):**
- `feedback_pm_validate_cli_in_cio_shell.md` (now in `offices/pm/knowledge/` per 2026-05-20 PM migration) — companion PM-side discipline: author acceptance criteria that include CIO's actual usage context.
- I-020 (V0.27.3 US-312 → V0.27.4 calibration.py path-bootstrap) — earlier analog, same lesson; PM-side fix.
- I-032 (V0.27.8 US-331 → V0.27.9 US-337 redo) — Tester-side analog; this memory's anchor case.
- I-037 (V0.27.10 US-330 canary false-positive → V0.27.11 redo) — Marcus-filed; same shape.
- **I-039 (V0.27.7 false-pass cluster, Tester-filed 2026-05-20)** — US-326 (drive_summary server analytics) and US-328 (drive_statistics Pi-side writer) both shipped `passes:true` in Sprint 33 but never deliver. Confirmed empirically across drives 11-18 incl. 2 fresh real drives today: server `drive_summary` rows all NULL on computed fields; Pi `drive_statistics` has 0 rows ever. US-330 (same V0.27.7 batch) also false-pass — absorbed by Atlas's F-8 finding (`boot-progress-finalize.service` ExecStop never pulled into shutdown transaction).
- **Atlas's F-7 (V0.27.15 sequencer boot-grace latch defect, 2026-05-20)** — different bug class but adjacent lesson: bench Cycle-A drills happened to dodge the failure conjunction (in-grace transient + post-grace level-stuck-LOW). Sprint 39 architectural correctness on clean-edge paths was real, but the IRL gate didn't exercise the suspected failure conjunction. **Tester-applicable extension**: when validating a refactor, ask "what failure conjunctions does this new design create, and do my IRL drills exercise them?" — not just "does the clean path work?"

**Bottom line discipline**: the post-condition that a fix produces the
expected new field/row/state in production data, observed via the consumer
seam that originally exposed the bug, is the only sufficient acceptance gate.
Synthetic / Python-mocked / clean-edge-only tests can pass while the real path
silently doesn't execute. This is the dominant failure mode of V0.27.x
sprints; harden against it before signing.
