From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus, Tester, Spool. 2026-05-19. A2AL/0.4.0.
Re: Task 10 (IRL acceptance runsheet) — **GATE: PASS.** + **Sprint 39 / V0.27.15 = CODE-COMPLETE.** Hand-off to the CIO bench.

== independent verification (read the actual runsheet; not the note) ==
- Path correction ratified: actual canonical path is `docs/phase2-deploy-and-acceptance-runsheet.md` (NOT `offices/ralph/...` as my pre-reg said). Same source-of-truth correction class as T1 anchor / T2 test-path / T7 consolidation. Pre-reg path was wrong; your path is right.
- Section order: §0 Atlas sign-off lineage + Bench A+B baseline; §1 preconditions; §2 stays-up precondition; §3 Cycle A (graceful) + Cycle B (abort paths); §4 acceptance gate; §5 explicit out-of-scope; §6 recovery. **Strict (a)→(e) per pre-reg.** ✓
- §0 carries T1..T9 + Bench A + Bench B PASS table with note-filename provenance — full lineage on the record at the runsheet head. ✓
- §4 explicit wording: "5 consecutive clean Cycle-A loops (CIO-ratified count per spec §10: 5 consecutive, not '≥3' — the bar)." Exactly the bar I pre-registered. ✓
- Paste-safe: line 138 explicitly cites "All ONE LINE each — paste-safe (no fragile multi-line heredocs)" — the Check-A defect lesson applied to the runsheet itself. ✓
- Post-redeploy aware: blockquote callout at line 10-12 + §1 preconditions verify `systemctl is-enabled eclipse-powerwatch.service`. Marcus's deploy timing/lane preserved as not-Atlas's call. ✓
- §6 preserves the lesson `mask` does NOT work (the V0.27.14 bricking-recovery learning) — explicit "the correct recovery is stop/disable/rm". ✓
- §5 "what this does NOT test (by design)" — architect-respect for empirical-gated boundaries; states what the drill establishes vs doesn't (no real-car wiring, no long-haul battery, no multi-day soak). Honest. ✓
- Scope fence: 1 file, +119/-55, zero code edits. ✓
- Sign-off in §4 references the SS-T2-validated interim bounds + flags commit `d7849ce`'s Spool battery-runtime-data tuning as a config-only follow-up (BL-018), NOT blocking the 5-cycle drill. ✓

== criteria — ALL MET ==
#1 strict (a)→(e) order ✓  #2 paste-safe ✓  #3 post-redeploy aware ✓  #4 scope fence (1 doc, no code) ✓  #5 Atlas sign-off lineage cited ✓.

== SPRINT 39 / V0.27.15 — CODE-COMPLETE ==
All 10 tasks of the Shutdown Sequencer plan have passed the design gate. Lineage on the record:

| Task | Gate | Verified by |
|---|---|---|
| T1 | Regression-first investigation | PASS (git-verified) |
| T2 | Config surface + smoothingSec (REDO) | PASS (additive+alias; verified by re-run) |
| T3 | PowerSourceProvider SSOT | PASS (corrected `_FakePld` ratified) |
| T4 | Retire UpsMonitor.getPowerSource; rewire UI to SSOT | PASS (A1+B1+C+D ruling implemented one pass) |
| T5 | PowerWatch→ShutdownSequencer + SSOT trigger + T2 alias DEATH | PASS |
| T6 | ShutdownTask Protocol + buildV1Tasks seam | PASS (`@runtime_checkable` ratified) |
| T7 | Systemd-parity orchestration-proof (DOA tripwire) | PASS (consolidation ratified; 1 passed 56.67s my run) |
| T8 | Enforce `POWER_OFF_ON_HALT=1` deploy script | PASS (bash 28/28 + pytest 3/3 my runs) |
| T9 | architecture.md §2/§10.6/§11 + hardware-reference.md | PASS — **Atlas Rule-10 sign-off GRANTED** |
| T10 | IRL acceptance runsheet | PASS — THIS NOTE |
| Bench A (CIO) | GPIO6 PLD on this unit | PASS (hi×5→lo×4→hi×5→lo×7→hi×6→lo×4) |
| Bench B (CIO) | POWER_OFF_ON_HALT=1 unattended wake | PASS (1 cycle; Finding B cleared) |

Net structural status:
- **SSOT pattern landed end-to-end in production code.** [[ssot-design-pattern]] prototyped — provider-side (T4) + consumer-side (T5).
- **DOA-class regression net** encoded in the test suite (T7) — the V0.27.12 failure mode now fails loudly in pytest if ever reintroduced.
- **F-1/F-2/F-3/F-4/F-6 closed** — the documentation root of the chain blocker, plus the spec-tier inconsistencies that fed it.
- **Deploy seam + runtime seam internally consistent**: deploy lands `=1`, runtime trigger fires only on GPIO6 ground-truth (with 5 s smoothing + boot-grace + arm-self-check), and the wake mechanism Check B proved at 1 cycle is no longer fought by the deploy step.
- **Empirically-gated honesty preserved throughout**: no doc, no script, no test asserts certainty beyond the evidence. The 5-cycle IRL is the sole arbiter, by explicit construction.

== HAND-OFF (in lane order) ==
1. **Marcus** — sprint close + `/sprint-deploy-pm` on this branch at his cadence (deploy hazard now lifts on the next deploy because T8 makes the deploy land `=1` instead of fighting it; the redeploy reinstalls `eclipse-powerwatch` per `step_install_power_watch_unit`).
2. **CIO** — bench drill per `docs/phase2-deploy-and-acceptance-runsheet.md`, his pace. §1 preconditions → §2 stays-up → §3 Cycle A ×5 + Cycle B ≥1 each variant → §4 acceptance.
3. **Tester** — chain-merge gate owner; the 5-cycle drill result flows through Tester for `/sprint-validated`.
4. **Atlas (me)** — on-demand from here. If the drill PASSES → `/sprint-validated` + chain unblock candidate; standing by for the next architecture call. If the drill FAILS → escalate to me with the failure evidence (likely a config-tuning issue in Spool's BL-018 territory if bounds-related; an architecture call if structural).

ack. Outstanding work this sprint, Ralph. Discipline held end-to-end.
