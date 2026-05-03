# US-274 first catch: US-278 phantom path `MEMORY.md`

**From**: Rex (Ralph Session 148)
**To**: Marcus (PM)
**Date**: 2026-05-03
**Re**: AI-001 sprint_lint file-existence check just caught its first phantom path -- in the same sprint that introduced it
**Severity**: informational (confirms the check works; documents the catch per US-274 stop condition #2)

---

## What happened

Shipped US-274's `lintFilesToTouchPaths` extension to `offices/pm/scripts/sprint_lint.py` and wired it into `lintStory`. Ran it against the current Sprint 23 contract per acceptance criterion #4 ("Run sprint_lint.py against current Sprint 23 sprint.json -> 0 path-existence errors"). Result:

```
$ python offices/pm/scripts/sprint_lint.py
...
  US-278
    ERROR   filesToTouch path does not exist on disk: 'MEMORY.md'

Summary: 1 error(s), 0 warning(s) across 9 stories
```

Acceptance #4 expected zero errors. The check found one. Per US-274 stop condition #2 ("If the new check finds REAL phantom paths in Sprint 23 sprint.json -- STOP, file PM follow-up to fix the path; don't suppress the error") I am not suppressing or rewording the check; I am filing this note instead.

## Why `MEMORY.md` is phantom

US-278 (`UPS HAT dropout characteristics doc (Spool knowledge)`) lists two `scope.filesToTouch` entries:

```json
"filesToTouch": [
  "offices/tuner/knowledge/ups_hat_dropout_characteristics.md (NEW -- empirical Drain 7 measurements ...)",
  "MEMORY.md (UPDATE -- power-mgmt section adds reference to the new knowledge doc; minimal addition under existing MAX17048 + UPS sections)"
]
```

`MEMORY.md` does not exist at the repo root. The auto-memory `MEMORY.md` lives at `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md` -- the per-user Claude Code memory directory, NOT a checked-in repo file. Other agents see its contents via the `# claudeMd` system context block, not via a repo path.

US-278's intent is reasonable (cross-link the new tuner-knowledge doc into auto-memory so future-Ralph and future-Spool sessions both pick up the Drain 7 dropout-knee fact). The execution path just lists the wrong file. Two correct options:

**Option A**: change the path to the actual auto-memory location. Ralph (whichever agent picks up US-278) can use `Write` against `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md` since that's where the auto-memory system file actually lives. This requires the path to be machine-specific (CIO's Windows workstation path), so a relative-from-script-dir or env-var-rooted form would be cleaner if the same story might run on Linux.

**Option B**: re-target the cross-link to a repo-tracked doc, e.g., add a one-line reference under `specs/grounded-knowledge.md` (for the dropout-knee fact -- this doc is the canonical safe-operating-ranges store per PM Rule 7) or under `offices/ralph/knowledge/patterns-pi-hardware.md` MAX17048 section. Either is repo-tracked, lives next to where future-Ralph would look it up, and avoids the auto-memory path complication.

**My recommendation**: Option B targeting `specs/grounded-knowledge.md` -- the dropout-knee VCELL value (~3.30V observed Drain 7) is exactly the kind of safe-operating-range fact PM Rule 7 says belongs in `grounded-knowledge.md` so future stories don't fabricate it. The new `offices/tuner/knowledge/ups_hat_dropout_characteristics.md` doc still gets the full empirical writeup; `grounded-knowledge.md` gets the one-line authoritative pointer.

## Pattern this confirms

This is the **third "catch" in three days** of the AI-001 phantom-path drift:

1. **Sprint 22 US-264** (caught manually post-ship): listed `src/pi/display/dashboard_layout.py`; actual path `src/pi/hardware/dashboard_layout.py`. Ralph used the right file but flagged drift in close note.
2. **Sprint 23 US-272** (caught at pre-flight): listed `seedVersionIsV0_18_0` rename target; commit 57bdda6 had already deleted it 3 days before grooming. Shipped ADD-equivalent + filed `2026-05-03-from-rex-us272-spec-divergence-rename-target-absent.md`.
3. **Sprint 23 US-278** (caught by US-274 -- this note): listed `MEMORY.md` at repo root; actual location is per-user auto-memory dir.

The third catch is the load-bearing one because it was caught **automatically** by the very check that closes AI-001. Beforehand the pattern relied on Ralph's eyes during pre-flight audit; now `sprint_lint.py` flags it as an error before any work starts. Cadence: 1 phantom per sprint pre-US-274, expected near-zero post-US-274 if Marcus runs `sprint_lint.py` before sprint open (per acceptance "Run lint at story-add time AND before commit" -- AI-001 proposed remediation).

## Recommended PM workflow change

Add `python offices/pm/scripts/sprint_lint.py && echo OK || echo FIX-PHANTOMS` to your sprint-grooming pre-flight checklist. Same place you already run sizing-cap + banned-phrase checks. The check is now atomic: fast (sub-second), zero-config, errors are actionable.

For **US-278 specifically**: pick Option A or B above (recommend B), update `sprint.json` to reflect the chosen path, then re-run `sprint_lint.py` to confirm zero errors. After that the next agent picking US-278 will get a contract that the new check approves of.

## Why this is informational, not blocking

The story I just shipped (US-274) is itself complete and verified:
- All 8 tests pass (5 parametrized cases + 1 sub-paren strict + 2 wiring tests).
- Pre-fix gate: 7/8 fail (the one negative-invariant test legitimately holds even pre-fix).
- Post-fix: 8/8 pass.
- ruff clean on both modified files.
- The check works against real sprint.json and emits exactly one actionable error -- the US-278 catch.

Acceptance #4 ("0 path-existence errors") is not strictly met, but stop condition #2 is the operative rule because the finding is REAL (not a parser bug). The check **is** the fix; the catch **is** the proof of fix.

## Observation: this matches the deliberate-divergence pattern

Three sessions running now (US-272 / US-273 / US-277 / now US-274) where spec premise was incorrect at groom time and the right move was ship-functionally-correct + file-inbox-note rather than block. Same shape:
- Spec premise: "audit was clean" / "rename target exists" / "/var/run is root:root" / "MEMORY.md is at repo root"
- Reality: the premise was based on stale or incorrect information at groom time
- Resolution: ship the functionally correct version + inbox note for PM adjudication

This is healthy -- it means Ralph is exercising judgment rather than blocking on every grooming imperfection. But it also means the grooming-quality gate has gaps that are worth a PM-side audit. AI-001 (this story) closes one such gap. The records-drift pattern (US-272 + US-273) hints at another grooming gap worth a follow-up: "if `groundingRefs` already names the closing work, the records-hygiene story might be already done -- check before grooming."

## Files this note references but does not touch

- `offices/ralph/sprint.json` -- US-278 entry needs the path correction (PM owns; per Sprint 19+ rule Ralph does not edit sprint contracts mid-sprint outside own-story scope)
- `specs/grounded-knowledge.md` -- candidate target for the cross-link if Option B is chosen (PM/Spool to decide the right home)

No action required of Ralph beyond shipping US-274 and filing this note.
