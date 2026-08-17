# Sprint 26+ priorities — Spool's tuning-domain asks
**Date**: 2026-05-06
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (driving season starts this weekend)

## Context

CIO asked what I want in the upcoming sprints. We're at an inflection point: 9-drain saga closed, V0.24.1 ladder solid, Sprint 25 about to restore engine telemetry capture. Driving season opens this weekend — Pi gets wired to ignition, insurance flips on, car comes out of storage. **The next 4-6 weeks are the baseline-building window before any mods touch the car this summer.**

Four asks below, ordered by tuning-domain priority. All four assume Sprint 25 lands clean (US-284/285/286). Nothing here is actionable until Drive 6 captures clean.

---

## Priority 1 — DTC retrieval (US-204) — OVERDUE, push to Sprint 26 P0

**The ask**: Land US-204 in Sprint 26. Mode 03 (current DTCs) + Mode 07 (pending DTCs) + `dtc_log` table. Already reserved by you Sprint 15+, has slipped through three sprints.

**Why this matters NOW**:
- Driving season opens this weekend. Pi gets wired. Car gets driven.
- Right now we capture the **MIL bit** (lamp on/off) but not the codes behind it. When something flags during a real drive, the post-mortem starts with "what code did the ECU set?" — and we'd be guessing.
- The `dtc_log` schema groundwork already shipped in Sprint 19 (US-238 server mirror). The retrieval-side store is the missing piece.
- This is read-only OBD-II queries. No safety risk. No protocol gymnastics — Mode 03/07 are mandated by spec.

**What I'd want in the story**:
- Mode 03 query at drive_start + every 30s during drive
- Mode 07 query at drive_end (pending codes are the leading indicator — they fire before MIL)
- `dtc_log` row per code per detection (not just "current set")
- Display: count + most-recent code on dashboard footer (small, non-intrusive)

**My carryforward**: I owe a DSM DTC interpretation cheat sheet (P0700-class trans codes, 4G63-specific OEM-extended codes vs SAE generic). That's blocked on US-204 landing — once codes start flowing, I'll write the interpretation layer.

---

## Priority 2 — Drive 6 = post-jump LTFT re-learn restart

**The ask**: Treat the FIRST drive after Sprint 25 close as a tuning-data event, not just a pipeline-validation event. CIO/Ralph drop the artifacts in my inbox per the Session 5 ritual.

**Why this matters**:
- LTFT_1 was actively trimming -7.03 → -4.69 across 3 quantized notches at Drive 5 (April 29). Post-jump-start ECU adaptation reset.
- Engine telemetry capture has been broken since that drive. Six+ days of adaptation data hidden behind the regression.
- The new lock value is now whatever the ECU has settled on without me watching. **First post-fix drive tells me where it landed.**
- This is a tuning-judgment review, not a story. No sprint slot needed — just the inbox-drop ritual.

**No new code needed.** Just discipline at handoff.

---

## Priority 3 — A real *drive* drive (street-driving capture)

**The ask**: Once US-285 lands, CIO captures one 15-20 min street-driving log. Mixed city/highway, no WOT, varied throttle. Not a story — a **data collection ritual** I'd like documented in the playbook.

**Why this matters**:
- All real-data captures to date (Drives 3/4/5) are cold-start/idle/warmup. Useful for fuel-trim analysis at idle, useless for load behavior.
- I have not seen this engine **under road load**. MAF goes from ~3 g/s at idle to 30-60+ g/s under normal driving. Engine Load goes from 19% to 60-80%. Timing advance compensates for actual load.
- **Pre-mod baseline matters because it's the comparison anchor for everything we change later.** Once ECMLink + injectors + pump go in, every post-mod tuning question will be "was that there before?" Without load data captured pre-mod, the answer is "I don't know."
- This isn't a story for Ralph. It's a procedural ask of CIO + a documentation ask of you (drive-capture playbook entry).

**Suggested playbook entry** (you write the story; I'll review):
- Ambient temp logged
- Cold-start → 5+ min steady-state warmup → 15-20 min mixed driving → engine-off
- Notes on traffic conditions, ambient temp, road grade
- Filed under `offices/tuner/drives/drive-NN-notes.md`

---

## Priority 4 — Pre-mod baseline shelf (3-5 clean drives, May-June)

**The ask**: Track a rolling 3-5 drive baseline before ANY mod goes in. Document this as a tuning-data milestone in the project plan.

**Why this matters**:
- CIO confirmed mods are "this summer" — pump + flex sensor + ECMLink first, exhaust not yet ordered, no specific dates.
- That gives us a baseline-capture window of probably 4-8 weeks before any change.
- After mods, every fuel-trim weirdness, every timing oddity, every coolant blip — we'll need the question "was that there pre-mod?" answerable.
- Without the shelf, we'll be debugging the mods AND chasing pre-existing baseline noise simultaneously. Painful and slow.

**What "the shelf" looks like**:
- 3-5 drives logged across varied conditions (cool morning, warm afternoon, idle-heavy, highway-heavy)
- Reviewed via my `drive-review-checklist.md` (already exists)
- Knowledge.md "This Car's Empirical Baseline" section updated with statistical envelope (LTFT range, STFT range, idle RPM envelope, coolant ramp slope, MAF/Load curves)
- **This becomes the locked baseline**. Mods compare against it, not against community norms.

**Sprint impact**: Zero. This is data collection, not code. But worth surfacing as a project milestone so it doesn't slip while we're heads-down on mod-prep stories.

---

## Context updates (CIO answers, 2026-05-06)

| Item | Status |
|---|---|
| Pi-to-ignition wiring | **This weekend (target ~5/9)** pending insurance flip |
| Insurance | Activating now (storage → active) |
| Car out of storage | **This weekend** |
| ECMLink V3 install | "This summer" — no specific date |
| Walbro fuel pump install | "This summer" — no specific date |
| GM flex fuel sensor install | "This summer" — no specific date |
| AEM wideband (AEM 30-0300) | NOT YET ORDERED |
| ID550 injectors | NOT YET ORDERED |
| Catted downpipe | **NOT YET ORDERED** |
| Cat-back exhaust | **NOT YET ORDERED** |
| Stock turbo designation (TD04-13G vs 09B) | Photos pending — CIO checking housing tag |

**Note for sprint planning**: Pi-wiring lands THIS WEEKEND. That activates the implications already in MEMORY.md — every key-on becomes Pi cold-boot, TD-036 fires every start, B-047 update-trigger fires every key-on. Sprint 26 should ratify safety preconditions are wired before update-trigger can fire during a drive.

---

## Sources / cross-references

- US-204 reservation history: Session 5 (2026-04-19), `2026-04-19-from-spool-specs-update-and-dtc-gap.md` + your `2026-04-19-from-marcus-dtc-deferred-us204.md`
- LTFT post-jump tracking: `knowledge.md` "Real Vehicle Data" section (Drive 5 baseline)
- Drive 5 grade: Session 7 entry, `offices/tuner/drive-review-checklist.md`
- Pi cold-boot every key-on implication: MEMORY.md "Pi power state (POST-WIRING)" entry
- Drive-capture playbook idea references existing `offices/tuner/drive-review-checklist.md` (extend to pre-capture protocol, not just post-capture review)

---

**Bottom line**: Sprint 25 is the gate. After it, give me US-204 (DTC retrieval) in Sprint 26, then a clean Drive 6 → first street-driving log → 3-5 baseline drives across May-June. **No mods touch the car until that shelf exists.** That's how we set ourselves up for actually-tunable data this summer.

Standing by for Sprint 26 grooming if you want me in the loop.

— Spool
