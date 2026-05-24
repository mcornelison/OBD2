From: Atlas (design gate — Rule 10 sign-off). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 9 (architecture.md + hardware-reference.md reconciliation) — **GATE: PASS. F-1/F-2/F-3/F-4/F-6 CLOSED on the spec side.** Atlas Rule-10 sign-off granted. Proceed to Task 10.

== independent verification (read the source, not just the note's excerpts) ==
- **§11 Wake-on-Power** at `architecture.md:1982-2005`: title "Wake-on-Power — Pi 5 + X1209-HAT topology (SS-T9, F-6 closed)"; `POWER_OFF_ON_HALT=1` locked (CIO 2026-05-18); topology rationale (HAT holds 5 V rail → PMIC never sees edge → Finding B); **Bench Check B (2026-05-18) at 1 cycle**; **5 consecutive cycles = IRL acceptance gate**; "until that gate passes, treat as designed-for and pending empirical confirmation, never as solved." The false `=0 ✅ auto-boot` table is GONE (grep clean). ✓
- **§10.6 Shutdown Sequencer** at `architecture.md:1639+`: title "Shutdown Sequencer (SS-T5, supersedes Power-Down Orchestrator)"; legacy ladder explicitly **deleted (commit `9adb0fb`, −1230 LOC)**; ShutdownSequencer flow narrated; **calibration lesson retained as superseded history** (40-pt MAX17048 SOC% error → VCELL truth → carries into `vcellFloorVolts`); deleted ladder body pointed to via `git log --reverse -p -- src/pi/power/orchestrator.py`. Elegant — keeps the doc small without losing the lesson. ✓
- **§2 SSOT narrative** at `architecture.md:99-116`: "exactly one authoritative provider: `PowerSourceProvider`"; **BCM GPIO 6, HIGH = power present** (vendor-confirmed); `UpsMonitor.getPowerSource()` **retired from power-source path**; "no second power-source acquisition path (SSOT invariant; Atlas design gate)"; **NotImplementedError tripwire** referenced as the loud-failure surface. ✓
- **hardware-reference.md**: F-3 — fictitious `0x08 Power Source` register **deleted**, replacement explicitly disclosed "previously listed a fictitious 0x08 Power Source register; it does not exist on the MAX17048 and never did" (line 108-110). F-4 — HAT identity **vendor-confirmed + Bench-Check-A PASS** (line 46-48, 542-543). Power-source line correctly redirected to GPIO 6 PLD / `PowerSourceProvider` SSOT (line 64, 71, 118). SS-T9 mod-history row at line 562. ✓
- **Scope fence**: `git show --stat c73ea91` => 2 files (specs/architecture.md + docs/hardware-reference.md), **+178/-312**. Zero code edits. README NOT touched (F-5 explicitly out of T9 per the plan). ✓
- **Honest empirical-gated language preserved**: §11 says "locked" (CIO) / "1-cycle confirmed" (Check B) / "5-cycle IRL still pending" / "drill is sole arbiter; no spec text or vendor doc overrides it." **No new false `=1 ✅` certainty.** Exactly the boundary the corrections-definitive file required.

== criteria — ALL MET ==
#1 BEFORE/AFTER excerpts (provided in note + I cross-checked source) ✓  #2 verbatim-equivalent to corrections-definitive ✓  #3 F-3/F-4 closed ✓  #4 honest empirical-gated language ✓  #5 mod-history + Last Updated ✓  #6 scope fence (2 files, no code) ✓  #7 Atlas review against corrections-definitive (this gate) ✓.

== **Atlas Rule-10 sign-off: GRANTED** ==
Per the design-gate DoD (PM Rule 10, CIO 2026-05-18): the load-bearing subsystem's `architecture.md` sections are updated in the SAME sprint that touched it. **F-1 (§10.6 stale), F-2 (§2 stale heuristic narrative), F-6 (§11 false EEPROM contract), F-3 (fictitious I2C register), F-4 (unverified HAT identity) all CLOSED on the spec side.** Marcus: this is the architect sign-off you administer as sprint DoD. Spec is now correct on the items the chain blocker rested on.

== minor follow-up (NOT blocking T9; doc-hygiene cleanup) ==
Grep surfaced two residual stale `PowerDownOrchestrator` references OUTSIDE §10.6's strict scope:
- `specs/architecture.md:172` (Component Architecture table — lists `PowerDownOrchestrator` as a component).
- `specs/architecture.md:417` ("US-216's `PowerDownOrchestrator` + US-217's...").

Scope-compliant for T9 (you correctly fenced to §2/§10.6/§11). But they will mislead a future reader who lands at §3 first. Same class as the post-T4 stale comments in core.py / test_power_monitor_db_write.py. **Add to the follow-up cleanup list, NOT a T9 defect.** Marcus FYI: a 2-line edit in a later doc-hygiene pass.

== CLEARANCE: proceed to Task 10 — the IRL acceptance runsheet ==
T10 = `offices/ralph/phase2-deploy-and-acceptance-runsheet.md` rewritten to spec §10 acceptance gate sequence, in order.

**Pre-registered Task-10 gate criteria (set now, before you start):**
1. Runsheet rewritten in this strict order:
   a. **Bench observations (T1 checklist) — already complete:** capture Bench A PASS (hi×5→lo×4→hi×5→lo×7→hi×6→lo×4, GPIO6 confirmed, `pldPowerPresentHigh=true` correct) and Bench B PASS (POWER_OFF_ON_HALT=1 confirmed, graceful poweroff, no button press, uptime≈5 min post-repower, Finding B cleared 1 cycle) as the in-runsheet baseline. These are not "to-do" anymore; they are the established preconditions.
   b. **Stays-up precondition** (boot N times on external power, confirm stays up > bootGrace + smoothing without self-poweroff; N to be ratified by CIO).
   c. **On-battery cycles**: sustained on-battery → window runs (sync when reachable; skip when not) → graceful poweroff → unattended restore on power return.
   d. **Acceptance gate: 5 consecutive clean unattended cycles** (CIO-ratified count from the spec; in-runsheet wording must explicitly cite "5 consecutive" as the bar).
   e. **Recovery procedure** if `eclipse-powerwatch` misbehaves (the stop/disable/rm sequence from the V0.27.14 incident).
2. The runsheet must be RUNNABLE on the actual bench, paste-safe (no fragile multi-line heredocs — lesson from the Check-A defect).
3. Each step uses commands that work against the **currently deployed state** OR explicitly notes "after redeploy" (deploy hazard remains; the runsheet operates POST sprint-deploy of this branch).
4. Scope fence: just the runsheet doc. NO code edits.
5. Cite Atlas sign-off lineage: Bench A + Bench B gates already PASS; T1..T9 PASS; chain unblock now gated only on T10 + the IRL drill itself.

Route the completion note when done; STOP for the gate. This is the **last task before the sprint hands off to the CIO bench**.

Unchanged: deploy hazard stands; chain BLOCKED until the 5-cycle IRL passes. ack.
