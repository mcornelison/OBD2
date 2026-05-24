# Tester Knowledge — Local Index

Tester-personal knowledge, feedback memories, and QA discipline notes. Per CIO memory-boundary directive 2026-05-20, agent-personal content lives here (not in `~/.claude/projects/.../memory/`, which is shared cross-agent + high-level project info only).

Detailed test reports / findings / gaps stay in their dedicated sibling folders (`../test-reports/`, `../findings/`, `../gaps/`); this folder holds standing lessons + role knowledge that persists across sessions and informs how I work.

## Feedback memories (testing discipline)

- [feedback-tester-validate-deploy-fixes-irl-not-just-code.md](feedback-tester-validate-deploy-fixes-irl-not-just-code.md) — Deploy-fix stories require IRL reproduction of the original failure path, not just "fix code is deployed" verification. I-032 lesson (V0.27.8 US-331 false-pass).
- [feedback-verify-service-restart-after-deploy-before-drill.md](feedback-verify-service-restart-after-deploy-before-drill.md) — Pre-drill MUST check service PID start time > deploy time. Code on disk ≠ code in memory. V0.27.16 lesson (eclipse-powerwatch ran V0.27.15 in memory while V0.27.16 files were on disk).
- [feedback-on-disk-journal-is-authority-not-live-tail.md](feedback-on-disk-journal-is-authority-not-live-tail.md) — Live `journalctl -f` over SSH dies unreliably across Pi power-cycles. Skip live tail; read on-disk `journalctl -b -1` after Pi reboots. V0.27.16 lesson.
- [feedback-i040-discipline-insufficient-for-writer-bug-class.md](feedback-i040-discipline-insufficient-for-writer-bug-class.md) — Stronger acceptance bars don't catch writer false-passes. Test surface needs deploy-context runner that exercises the integrated orchestrator + DriveDetector + recorder against a real DB. V0.27.16 US-348/349 lesson (3rd recurrence).
- [feedback-lane-discipline-formalized-in-settings.md](feedback-lane-discipline-formalized-in-settings.md) — CIO's 2026-05-20 lane-discipline rule is now ENFORCED as permission boundaries in settings.local.json. Cross-office facts arrive via inbox; I no longer read other agents' non-inbox files directly. V0.27.18 reinforcement 2026-05-22.
- [feedback-tester-commits-not-pushes-pm-owns-remote.md](feedback-tester-commits-not-pushes-pm-owns-remote.md) — Tester (Argus) git lane is COMMIT-ONLY. PM (Marcus) owns ALL remote pushes + merges. CIO directive 2026-05-22 after I over-pushed 4 times during /sprint-validated session. Settings updated to deny git push/merge.

## Conventions

- One memory per file; descriptive kebab-case filenames.
- Frontmatter `name` / `description` / `type` mirrors the shared-memory format so semantics are preserved across the boundary.
- When a memory is migrated FROM shared memory, frontmatter records `migratedFrom` + `migratedOn` + `migrationReason` for traceability.
- Cross-references to memories that now live in other agents' knowledge folders are noted with their new path.
