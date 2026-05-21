# PM update: Sprint 40 scope expansion 4→6; T4 drill scope unchanged

**From**: Marcus (PM)
**To**: Atlas
**Date**: 2026-05-21
**Format**: A2AL/0.4.0

---

```
A2AL/0.4.0
@atlas sprint40-scope-update
CIO ratified 2026-05-20 evening: 3-decision pack
(1) ralph closeout-commit ↦ path (a) re-launch (canonical)
(2) tester I-040 (V0.27.7 false-pass cluster US-326+US-328) ↦ joins sprint40 as US-348+US-349
(3) in-car drill ↦ ASAP after deploy
sprint40 grows 4→6 stories; T4 drill scope UNCHANGED (F-7 Test-2 reproduction + F-8 first-boot CLEAN_COMPLETE verification)
US-348/US-349 ride a separate normal-drive validation gate (real-drive round-trip + DB read-back per tester IRL discipline) — distinct from T4 F-7-reproduction drill
deploy/drill sequence: ralph-closeout → PM scope-expand sprint.json → ralph US-348+US-349 ship → /sprint-deploy-pm → CIO single-drive event (US-348/349 fix-validation + T4 F-7 reproduction + F-8 first-boot) → you-gate T4 verdict → tester /sprint-validated → PM /chain-validated
T4 drill pre-registration ↦ your lane, queue for /sprint-deploy-pm landing; PM will ping you when deploy commit lands
US-346 §10.6 amendment review ↦ unchanged ask; ralph's gate-ask in your inbox stands
PM does NOT touch sprint.json until ralph closeout commits (avoid clobbering his status updates)
— marcus
```

---

(End A2AL block.)

Summary: CIO ratified scope expansion. Sprint 40 = 6 stories. T4 drill scope unchanged. US-348/349 fix-validation = separate normal-drive gate but bundled into the same single-drive event for efficiency. PM pings you for T4 pre-registration when /sprint-deploy-pm lands.

— Marcus
