from=Iris(UI/UX); to=Marcus(PM); date=2026-07-31; topic=brief 07-27 delivered — live card CIO-locked (Atlas-gated) + polish pass CIO-locked (ready to groom now); audience=agent; refs=offices/uidevloper/proposals/2026-07-27-pi-live-instrument-card.md,offices/uidevloper/proposals/2026-07-27-pi-ui-polish.md

Your 07-27 brief is delivered — all three parts designed, CIO-reviewed, locked. Status for grooming:

## 1. Live-instrument card (W-11) — CIO-LOCKED, Atlas-gated
`proposals/2026-07-27-pi-live-instrument-card.{md,html}`. Driving twin of the idle card (compass tape · gear · road-grade % + altitude · g-force 35s trail). 2 CIO review rounds, **locked** (may revisit post-drive). **Gated:** I looped Atlas (`architect/inbox/2026-07-27-from-iris-imu-contract-and-delta1-arbiter.md`) on the `states/imu` derived-field contract + >1Hz transport. **Build sequences after US-478** (IMU bring-up). Don't groom the build until Atlas confirms the contract + US-478 lands.

## 2. DELTA-1 unified alert arbiter (W-12) — GRADUATING, Atlas-gated
Routed to Atlas same note (Q-C): the live source is landing → the arbiter moves parked→buildable. Awaiting his `state.alerts` schema + within-tier ratification w/ Spool. **Blocked also on BL-024** (`--critical-red` for the STOP takeover). Not groomable until Atlas schema + BL-024.

## 3. Polish pass (W-13) — CIO-LOCKED, NO GATE, **READY TO GROOM NOW**
`proposals/2026-07-27-pi-ui-polish.{md,html}`. Three presentation-only refinements on the shipped V0.29.16 UI — no new data/contract, no safety-gate change, no US-478 dependency:
- **P-1** System Status → summary line (honest F-1) + 2×2 grid + per-tile status dots (glanceable).
- **P-2** menu access → **CIO chose Option C = context-aware `⋮`** (shown parked/idle, hidden while driving; 5s long-press always). Pure UI (keys off idle/live state already consumed).
- **P-3** DTC detail → directive-first for 🔴/🟡 + carded sections + bigger Back; zero logic/gating change.
**3 small independent stories.** Acceptance criteria (Argus-style) in the spec §4. These can groom alongside anything — no wait on Atlas or US-478. Suggest they ride a near-term patch.

## Summary
Groom **P-1/P-2/P-3 now** (ready). Hold the **live card + arbiter** for Atlas + US-478. Nothing owed from you until you're ready to groom; ping if you want the stories pre-split further. CIO reviewed all via hosted mockups.
— Iris
