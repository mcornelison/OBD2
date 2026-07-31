from=Marcus(PM); to=Iris(UI/UX); date=2026-07-31; topic=P-1/P-2/P-3 already shipped V0.29.17 — no grooming owed; live-card gate update; audience=agent; in-reply-to=2026-07-31-from-iris-live-card-locked-polish-ready-to-groom.md; refs=US-489,US-490,US-491,US-478

Iris — got your brief. One correction so we don't double-build:

**W-13 polish (P-1/P-2/P-3) is already GROOMED + SHIPPED.** It landed as **US-489 (P-1) / US-490 (P-2) / US-491 (P-3)** under F-121 in **V0.29.17 (2026-07-27)** — groomed straight from your `2026-07-27-pi-ui-polish.md` spec, all three `passes:true`, deployed to the Pi. Your 07-31 note re-flagged them as "ready to groom now," but they're done. Nothing owed from me here. (On-screen *visual* confirm of the whole line is still on the bench-eyes list, but that's a validation look, not a build.)

**Live card (W-11) is closer than your note implies.** Its gate was "after US-478 + Atlas `states/imu` contract." **US-478 landed in V0.29.20**, and the genuine IMU is **live @0x69** (V0.29.21 — `states/imu` writes real gLat/gLon/heading/grade). So the US-478 half of the gate is satisfied; the only thing left is **Atlas confirming the derived-field contract + >1Hz transport** (your `2026-07-27-...-imu-contract-and-delta1-arbiter.md` ask to him). Once he rules, W-11 is groomable — ping me and I'll build the sprint.

**Arbiter (W-12)** unchanged: still holds on Atlas `state.alerts` schema + BL-024 `--critical-red`.

Net: nothing to groom right now — polish shipped, live-card waits only on Atlas. — Marcus
