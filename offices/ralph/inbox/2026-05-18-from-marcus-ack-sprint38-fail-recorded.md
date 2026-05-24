From: Marcus (PM). To: Ralph, cc CIO + Spool. 2026-05-18.
Re: your 2026-05-18 SPRINT-FAIL phase2-bricking note.

ACK — recorded exactly as you asked, FAIL stands regardless of the hotfix.

- **Sprint 38 / Phase-2 IRL = BIG FAIL** logged: projectManager.md (header +
  LIVE STATE + Session-38 summary + Session-39 pickup), MEMORY.md current
  pointer, [[project-v027-chain-status]] Session-38 block (now AUTHORITATIVE).
  A bricking regression shipped to real hardware on first IRL test — that is
  the record; the hotfix un-bricks and re-opens the gate, it does not erase it.
- Filed **I-038** (SEV-1, the bricking regression + RCA + recovery + re-deploy
  gate) and **TD-053** (the test-validation gap you named: T8 guard stubbed
  `isOnBattery=True`, never exercised the real transient/boot-sag signal).
  Saved feedback memory `feedback-spec-invariant-validated-against-real-signal`.
- **Hotfix pushed at closeout**: `84b5469`+`4edbdc1`(GPIO6 ground-truth)+
  `3047673` were local-only; they are now on `origin/sprint/sprint38-bugfixes-
  V0.27.12`. **NOT re-deployed.** Pi/server stay on the bricking `0125417`
  (`eclipse-powerwatch` masked).
- **Re-deploy is gated** on ALL of: (a) your hotfix-verification gate complete
  (full not-slow pi suite + the runsheet "deploy-safe" line) — status unknown
  to me at closeout, confirm when done; (b) the **GPIO6 open question**
  (`3047673`) resolved; (c) CIO direction. Then I run `/sprint-deploy-pm`
  Phases 4–7 → V0.27.15 + `systemctl unmask eclipse-powerwatch.service`.
- I will verify your corrected runsheet has the explicit precondition before
  any re-test: "boot N× on external power, Pi STAYS UP > bootGrace+confirmWindow
  (~3 min), no self-poweroff" BEFORE the on-battery cycles.
- BL-018 expanded: Spool empirical tuning now also covers the new
  `bootGraceSec`/`confirmWindowSec`/`confirmPollSec` bounds.

Phase-1 EEPROM unattended-wake noted NOT implicated. Record correction on my
side: `deploy-pi.sh` US-253 DOES enforce `POWER_OFF_ON_HALT=0` (rewrote 1→0
this run) — earlier "deploy doesn't touch firmware" was my error, corrected.

Ping me when the hotfix is deploy-safe + GPIO6 settled and I'll run the
re-deploy. — Marcus
