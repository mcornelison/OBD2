From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Task-1 checklist-defect correction + deploy-state lesson — **DONE, routed for gate.**

The owed parallel deliverable (tracked across the last 3 gates) is complete.

## Commit
Branch `sprint/sprint39-bugfixes-V0.27.15`, **`61e1ada`** (2 files, +103/-21):

1. **`offices/ralph/phase2-bench-observations-checklist.md`** — Check A replaced
   with the dependency-free OS `pinctrl` form (`sudo pinctrl set 6 ip pn` +
   `pinctrl get 6` loop; `raspi-gpio get 6` legacy fallback). **No project
   import, paste-safe, no deploy** (deploy hazard explicitly restated). The
   "available=False / install gpiozero" row is **dropped** (no project import =
   not relevant). Binary / escalate-to-Atlas table form kept. Check B left
   unchanged (OS-only). Added a STATUS line recording the bench PASS
   (hi×5→lo×4→hi×5→lo×7→hi×6→lo×4) since the corrected form already ran green.

2. **`offices/ralph/findings/2026-05-18-bench-instrument-deploy-state-lesson.md`**
   — one page, git-cited (Pi runs deployed `0125417`; `git ls-tree 0125417 --
   src/pi/hardware/pld_sensor.py` ABSENT; module created by undeployed
   `4edbdc1`). Lesson: a validation/bench instrument is code that must run
   as-wired on the target's ACTUAL deployed state, not the repo branch — same
   failure class as V0.27.12-DOA ("written, but not where it runs"); generalizes
   spec §5 orchestration-proof to the validation tier. Adopted 4 concrete rules
   (no project imports on deploy-divergent targets; paste-safe; state deployed
   SHA + `git ls-tree` verify; deploy-hazard is not a workaround path).

## Invariants / discipline
- Task-1 regression conclusion **unchanged** (not reopened — git-verified, stands).
- Scope-fenced: only the 2 artifacts in `61e1ada`; the checklist's linter-applied
  bench-result marks were preserved (not reverted), committed with the correction.
- Deploy hazard honored: the corrected instrument works against the *current*
  deployed state without changing it; no redeploy/unmask implied or required.

No gate-blocking needed (Atlas said this is a parallel deliverable-correction,
not stop-the-world). Surfacing for your gate record. Per CIO direction I am now
**proceeding to Task 3** (`PowerSourceProvider` SSOT) and will STOP at its gate. — Ralph
