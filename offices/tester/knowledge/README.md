# Tester Knowledge — Local Index

Tester-personal knowledge, feedback memories, and QA discipline notes. Per CIO memory-boundary directive 2026-05-20, agent-personal content lives here (not in `~/.claude/projects/.../memory/`, which is shared cross-agent + high-level project info only).

Detailed test reports / findings / gaps stay in their dedicated sibling folders (`../test-reports/`, `../findings/`, `../gaps/`); this folder holds standing lessons + role knowledge that persists across sessions and informs how I work.

## Feedback memories (testing discipline)

- [feedback-tester-validate-deploy-fixes-irl-not-just-code.md](feedback-tester-validate-deploy-fixes-irl-not-just-code.md) — Deploy-fix stories require IRL reproduction of the original failure path, not just "fix code is deployed" verification. I-032 lesson (V0.27.8 US-331 false-pass).

## Conventions

- One memory per file; descriptive kebab-case filenames.
- Frontmatter `name` / `description` / `type` mirrors the shared-memory format so semantics are preserved across the boundary.
- When a memory is migrated FROM shared memory, frontmatter records `migratedFrom` + `migratedOn` + `migrationReason` for traceability.
- Cross-references to memories that now live in other agents' knowledge folders are noted with their new path.
