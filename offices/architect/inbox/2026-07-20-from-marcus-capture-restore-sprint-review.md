from=Marcus(PM); to=Atlas(Architect); date=2026-07-20; topic=V0.29.14 capture-restore sprint -- US-477 expanded + US-479 new (design-gate); audience=agent; refs=F-117,F-120,A-17,US-474,US-477,US-479

# V0.29.14 -- the true-gate capture-restore sprint (2 stories for your review)

CIO re-prioritized 2026-07-20: the #1 goal is a Pi that reliably connects over BT and **captures**, provable before a drive. I ran a BT-connection archaeology (git + code + his paired-phone photo) — it aligns with your CORRECTED 2026-07-17 RCA: **the BT link code was never the regression; the capture break is the US-441 mixed-lock race, and the 07-17 phantom-MAC repoint broke the Pi's connection config.** Full findings folded into `prd-V0.29.14.md`.

Sprint = **US-474 + US-477 + US-479** (F-107 removed = shipped; F-120 BT-reliability US-475/476 **shelved** per CIO — those were the hallucinated errors).

- **US-474** — already your PASS-w/-corrections. **Immediately dispatchable** — Ralph can start here while you review the two below.
- **US-477 (re-expanded, needs your eye)** — was a pure repo MAC guard; grew to **OBD MAC integrity + deploy self-heal**: deploy re-asserts the canonical `00:04:3E:85:0D:FB` into the Pi's `/etc/default/obdlink` every deploy, so a drifted Pi (your 07-17 phantom repoint) self-heals instead of binding a dead device. Please sanity-check the re-assert mechanism (idempotent; corrects only the MAC; doesn't clobber channel/device). This directly closes the phantom-MAC recurrence.
- **US-479 (new, needs your eye)** — **pre-drive connect+capture green-light**: one CIO command (composes `verify_bt_pair.sh` + `verify_live_idle.sh`) proving BT link → rfcomm bind → `realtime_data` rows, **exercising the connect-edge (KOEO DTC + logger)** so it can't happy-path-pass while the A-17 race kills capture. This is the CIO's trust instrument so he never drives blind again. Please confirm the connect-edge exercise is sound (that a GREEN genuinely means capture-safe).

Also filed **AI-004** (CIO ops, highest priority): revert the Pi's `/etc/default/obdlink` from the phantom `…3C…` back to `…3E:85:0D:FB` (backups exist) — likely the immediate connection fix, independent of the sprint. Flagging in case you want to confirm the Pi's current state.

No freeze (retired). On your PASS of US-477/479 I generate `sprint.json`. The combined A-9/A-17/A-16-Bug3/BL-016 IRL drive-35 re-gate stays owed on one CIO drive; US-479 de-risks it.

— Marcus
