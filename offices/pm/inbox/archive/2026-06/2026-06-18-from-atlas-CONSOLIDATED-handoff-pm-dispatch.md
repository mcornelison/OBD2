# CONSOLIDATED hand-off → PM: two sprints + open items ready for you to dispatch

**Date**: 2026-06-18
**From**: Atlas (Architect)
**To**: Marcus (PM)
**Why this note**: CIO clarified I should stay in the architecture lane — I drifted into sprint
mechanics this session. Handing all dispatch-ready work back to you in one place so you can kick it
off for Ralph. The architecture/design/triage is done; the grooming → freeze → Rule 13 → dispatch →
merge is yours.

---

## 1. EDR bus — Slice 1 (READY to groom + dispatch)
The dedicated-reader → in-process bus → PersistenceSubscriber pipeline (gate #1 of the EDR epic, A-14).
- **Draft sprint:** `docs/superpowers/plans/2026-06-18-edr-bus-slice1-sprint.draft.json` (6 stories, v2.0.0, UNFROZEN)
- **Spec:** `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- **TDD plan (complete code):** `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- **Prior grooming note:** `2026-06-18-from-atlas-edr-bus-slice1-ready-to-groom.md`
- **Key facts:** ships DARK behind `pi.bus.enabled` (zero behavioral change on merge); byte-identical
  `realtime_data` golden-master is the gate; hardware-independent (buildable now). Proposed F-EDR-BUS / E-006.

## 2. A-9 DriveDetector — RCA + fix (READY to groom + dispatch)
A-9 REOPENED — the dual-attribution + open-drive-leak defect recurred on drives 28/29 (F-107 incomplete).
- **Draft sprint:** `docs/superpowers/plans/2026-06-18-a9-drivedetector-rca-sprint.draft.json` (4 stories, UNFROZEN)
- **Finding (evidence):** `offices/architect/findings/2026-06-18-drivedetector-defect-recurs-28-29.md`
- **Prior grooming note:** `2026-06-18-from-atlas-a9-rca-sprint-draft-ready.md`
- **Key facts:** HIGH severity but NOT a chain block (server tripwire backstop verified working). It's an
  RCA — US-388 (fix) is **build-blocked on US-387 (RCA)**, keep it "shape pending" (don't freeze fix detail).
  In-process reproducer needs no hardware; sprint-level IRL (short/back-to-back + key-on-after-missed-close)
  is CIO/Argus-gated. Proposed under F-107 / E-002.

## For BOTH sprints — your mechanics (mine noted)
- Mint real US-/F-/E- IDs via `story_counter`; run the `prd_to_sprint.py` freeze; **request my Rule 13
  sign-off** before dispatch (I'll turn it fast).
- Ralph courtesy pointers are already in his inbox, both marked **"await PM dispatch."**
- Sequence/priority is your call (EDR slice vs A-9 RCA vs US-367).

## 3. Sprint 45 closeout + branch state (your ritual)
- Ralph re-verified Sprint 45/V0.28.2 done (2/2, no new work, no merge). Already on main since 2026-06-05.
- **`dev` is ~56 ahead of `origin/main`** — a chain's worth of accumulated work awaiting your integration cycle.
- Archive `sprint.json` + prep next sprint + integrate `dev → main` when ready. Detail:
  `2026-06-18-from-atlas-sprint45-closeout-state-handoff.md`.

## 4. Open items needing your tracking/scope (not sprints yet)
- **chi-srv-01 IP fix** deployed to Pi (sync restored, verified) — but **PM-owned docs still have stale `.10`**:
  `roadmap.md:111`, `projectManager.md` (mixed), `tech_debt/TD-006`. Memory `MEMORY.md` infra line too.
- **`dtc_freeze_frame` sync HTTP 500** — latent server bug unmasked by the IP fix; needs a server-side issue
  Story. Detail: `2026-06-18-from-atlas-issue-dtc-freeze-frame-sync-500.md`.
- **A-15 mirror-drift follow-ups** routed: config.json de-dup (gap → Ralph) + hostname-resolution (design Story).

---

**Atlas posture: on-demand architecture.** I'll do Rule 13 sign-offs, design rulings, and triage on
request. Dispatch, freeze, merge, and closeout sequencing are yours. Ping me when you want the Rule 13
passes on either sprint.

— Atlas
