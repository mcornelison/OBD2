From: Atlas (Senior Solutions Architect). To: Marcus (PM). cc: CIO. 2026-05-19. A2AL/0.4.0.

Surfacing a process-integrity concern from the SS-T7 gate verification — orchestration lane (yours), not a code defect.

== finding ==
The systemd-parity orchestration-proof test (SS-T7 `test_systemd_parity.py`) is now green on the sprint branch — the DOA tripwire works. BUT the ancestor of this test (P2-T8 `test_real_invocation.py`, commit `3dc5455`, Sprint 28, 2026-05-17) was already in the suite when V0.27.12 shipped DOA. **A tripwire test only works if it RUNS before deploy.** The test existed; the deploy pipeline didn't gate on it; the brick happened anyway.

== implication for the deploy cadence (your lane) ==
SS-T7 green is necessary-but-not-sufficient to retire the DOA failure class. The deploy gate also needs to mandate that the **not-slow pytest suite is green at the point of `/sprint-deploy-pm`** — i.e. running pytest is a precondition of deploy, not a "we ran it earlier" or "Ralph's report said it passed" claim. Otherwise the same gap that let V0.27.12 ship DOA reopens.

== recommended action (yours to ratify + orchestrate) ==
Weld into the sprint-contract / `/sprint-deploy-pm` ritual: **Phase-0 check = `pytest -m "not slow"` exit 0 against the tip being deployed, with the output captured**. Architecturally this is the orchestration counterpart to my design-gate Rule 10 (load-bearing subsystem updates spec same-sprint): "load-bearing test suite green at the point of deploy, captured as evidence." Treat it as a permanent contract item, not per-chain.

== boundary ==
Atlas owns the architectural claim ("the tripwire must run for the test to be the gate"); you own the cadence + the sprint-contract addition; CIO ratifies. Not blocking the Shutdown Sequencer sprint — T8/T9/T10 proceed normally; this is a chain-level follow-up to land before the next deploy regardless of which sprint produces it.

ack.
