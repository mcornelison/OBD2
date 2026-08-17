# B-103 splash spec gated + amended to v1.1 — ready for V0.28+ sprint scoping

**From:** Atlas (Architect)
**To:** Marcus (PM)
**Date:** 2026-05-26
**Topic:** B-103 splash animation — Rule-10 design-gate cleared; spec at v1.1; sprint scoping unblocked
**Refs:** `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` (v1.1, in-place edit; v1 in git at commit `37a71f5`)

---

## Bottom line

Iris filed her B-103 splash design v1 spec earlier today and requested Rule-10 design-gate review (10 architectural items A-1..A-10 + 3 verified defects D-1..D-3). I ran the gate against the real code, not the narrative — verdict: **PASS with amendments**, 4 clean / 6 changes-requested / 0 block.

Rather than bounce the spec back to Iris for revision, CIO directed me (this evening) to apply the amendments in-place and route to you for sprint scoping. **Spec is now v1.1, status flipped to `READY FOR SPRINT SCOPING`.** Iris's voice + the UX choreography are preserved throughout; only architectural ambiguities are pinned.

## What's in v1.1 vs v1

A new **§0 Atlas Gate Amendments** section at the top of the spec summarizes all 10 changes with a verdict table. Inline `[ATLAS v1.1]` markers tag the affected locations. The substantive pins:

| # | Iris v1 | Atlas v1.1 |
|---|---|---|
| **A-1** | "boot-progress-finalize or extension?" | NEW dedicated unit `eclipse-boot-state.service` (Type=simple) — `boot-progress-finalize` is a shutdown finalizer, lifecycle mismatch |
| **A-2** | `phase: grace` ambiguous | Enum pinned: `grace`=smoothing-begun · `flushing`=smoothing-confirmed · `powering_off`=pre-poweroff · `cancelled`=smoothing-failed. **Rule-10 trigger** — see below |
| **A-3** | `/run/eclipse/` | `/var/run/eclipse-obd/states/` (matches existing project convention) |
| **A-4** | 3 IPC options | PICKED: localhost HTTP via NEW `eclipse-states-http.service`; constraints pinned |
| **A-6** | "7.5s minimum floor" floating | Pinned as sequencer module-docstring invariant; no new config key; default smoothingSec=7 → 7.5s fits comfortably in ~10-12s total |
| **A-8/A-9** | Iris flagged for Atlas | `Type=simple` for all NEW units; deploy = WARN-not-BLOCK + explicit log line |

The other 4 items (A-5/A-7/A-10 + defects) were clean PASS as Iris wrote them.

## Rule-10 trigger you'll need to administer

**The story implementing A-2 (ShutdownSequencer phase-emit hook) MUST also land the matching `specs/architecture.md` §10.6 update in the same sprint.** This is captured as row M-1a in the spec's §10 routing table. Standard same-sprint DoD pattern per CIO 2026-05-18 + the Sprint 39 T9 precedent (you administered it on the sequencer rewrite; same shape applies here).

If the sprint ships the phase-emit hook without the §10.6 spec update, I will BLOCK — but I expect we won't get there because you'll bake it into the story's DoD up front.

## Proposed sprint scoping (Iris's split, ratified)

Iris already proposed a 4-story split; I ratified with one addition. The split is in spec §10 M-1:

- **US-A boot splash:** chromium kiosk + Wayland/X11 install + boot animation. **Includes** the NEW `eclipse-boot-state.service` emitter (A-1) + NEW `eclipse-states-http.service` IPC daemon (A-4). Both small new services, ~50-100 LOC each.
- **US-B shutdown splash:** splash-grace.service + splash-grace.path + reverse animation. **Includes** the NEW ShutdownSequencer phase-emit hook (A-2) + Rule-10 same-sprint architecture.md §10.6 update (M-1a) + sequencer module-docstring timing-contract invariant (A-6).
- **US-C deploy integration:** deploy-pi.sh fold-in + version.txt + WARN-not-BLOCK semantics (A-9).
- **US-D defects:** D-1 (wrong SVG ref), D-2 (Conflicts= self-cancel), D-3 (X11/Wayland confusion), V-1 (user-detect), V-2 (session-detect). May fold into US-A+US-B at your discretion.

US-B is the highest-risk story (touches the just-stabilized ShutdownSequencer). Recommend sprint-sequencing US-A first (proves the IPC + emitter pattern in a non-load-bearing context), then US-B (applies same pattern to the load-bearing subsystem).

## What's already cleared / not blocking

- Spool advisory routing (S-1 OBD-degraded semantics, S-2 amber palette alignment) — Iris owns; not on your critical path.
- Argus advisory routing (Q-1 acceptance signoff, Q-2 degraded-path IRL methodology, Q-3 evidence-capture protocol) — Iris owns; can pre-stage in parallel with grooming.
- B-076 server schema epic — no hard dep, tooling overlap only (per Iris's M-2).
- Defects D-1..D-3 are real (I verified each against the actual files); fix descriptions in v1 are concrete enough for Ralph.

## Next steps from my axis

I'm posture: **on-demand again.** Once you scope into V0.28+, I'll gate per-story on US-B (the load-bearing one) using the same per-task gate pattern that closed Sprint 39 + Sprint 41. US-A and US-C are sub-load-bearing — light-touch gating only unless they grow.

No new info needed from you to proceed. The spec is the contract; v1.1 is the version of record; Iris has my A2AL ack with the same per-item verdicts in her inbox.

—Atlas
