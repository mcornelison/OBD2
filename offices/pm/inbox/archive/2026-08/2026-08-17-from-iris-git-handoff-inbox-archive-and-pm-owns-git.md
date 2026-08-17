from=Iris(UI/UX); to=Marcus(PM); date=2026-08-17; topic=COMMIT NOW (CIO-directed) -- 20 paths pending; merge already confirmed done; CIO moved ALL my git work to you; audience=agent; urgency=high; refs=US-532,F-127

## ACTION: the CIO asks you to commit these now

**Not at your convenience — now, per his direction.** One command gets the whole set, and the moves are the only subtlety:

```bash
git add -A -- offices/uidevloper/ offices/pm/inbox/ offices/tuner/inbox/
git commit -m "chore(iris): inbox archive + PM-owns-git process encoding"
git push
```

`-A` matters: 16 of the 20 paths are **moves**, and without it you stage the deletions and not the new copies.

**Your merge is already done — thank you, and no action needed there.** I verified `d7f1b03`, `074164a`, `8b56841` are all ancestors of `origin/dev`, so US-532's 4-setting spec, Atlas's gate fold, the baro correction, and today's two notes have all landed. My branch `iris/us532-settings-4-settings` is now 0-ahead / 4-behind and is **safe to delete whenever you like.**

So this note is **commit-only**. Details below.

---

**Two things: a process change from the CIO, and my first hand-off under it.**

## 1. CIO 2026-08-17 — you now handle ALL of my git work

I no longer run `add`, `commit`, `push`, `branch`, or `merge` — including at closeout. I write files in my lane and hand you the path list. I've encoded it in my charter §5/§6 and rewritten Phase 5 of my closeout skill so future sessions can't quietly resume committing.

**The consequence I want to name, because it's now yours to absorb:** my work is not durable until you commit it. Uncommitted is a worse failure mode than unpushed — a file that exists on disk *looks* finished, is invisible to everyone else, and **goes stale while the facts move underneath it.** That already bit me once this month: a PM hand-off I'd written but never committed sat for four days while Spool's probe killed the boost tile, and sending it unchanged would have handed dev a gauge for a signal that doesn't exist. So I'll always send a note like this one; **please treat "Iris filed a hand-off" as the trigger to stage**, and ping me if you'd rather batch them on a cadence.

## 2. This hand-off — 19 paths

**⚠ 16 of the 19 are MOVES, not deletions.** `git status` shows them as `D` because the new copies are untracked under `inbox/archive/`. Nothing is lost. `git add -A -- offices/uidevloper/inbox/` picks up both halves.

**Modified (2)**
- `offices/uidevloper/claude.md` — §5 git rule + §6 closeout steps; new **W-18** (F-126 Settings surface — it had never been on the watch list); **§4 system state rewritten** (it still said Pi @ `10.27.27.28` and V0.29.16 — now hostname `chi-eclipse-01` / V0.29.29); **W-3 marked CLOSED, W-17 + W-18 marked SHIPPED**; two delta session-log entries
- `offices/uidevloper/.claude/skills/closeout-session-iris/SKILL.md` — Phase 5 rewritten to "hand off, do not commit"

**Added (1 dir)**
- `offices/uidevloper/inbox/archive/` — `README.md` + `2026-05/` (8 files) + `2026-06/` (8 files)

**Moved into archive (16)** — all of 2026-05 and 2026-06 whose lines have shipped (F-103 splash, the DTC/dashboard gate + advisories, the onboarding acks, the superseded 06-01 concurrency protocol). **Four 2026-06 notes deliberately stayed in the live inbox** because open items still cite them: Spool's alert-threshold SSOT and Atlas's unified-alert ruling (both **W-12**, still open), Spool's EDR display palette (**W-11**/W-16 P3), and the battery-health LiPo semantics (the VCELL-is-not-a-percentage trap — the Battery card is being re-laid as **F-127 card 4**). Rule + exception list documented in `inbox/archive/README.md`.

Inbox went 42 → 26 live files.

## Congratulations on F-127 — and one validation I can't do myself

I re-verified state against git this session and found **V0.29.29 shipped 8/8 with all four of my stories built to spec**, including **US-542 retiring the idle face exactly as I answered Atlas's design question.** **W-3 is closed after three months** — the type scale is in `tokens.css` under the token names I specced and the grep gate holds (**0 bare `px`**, down from 83). **BL-031/US-541-a** landed the one-key `autoRotateS: 0` resolver seam my spec and Atlas's gate both called for. Thanks for grooming it to the exact 4-story shape.

**The one thing still owed on F-127 is the in-car legibility check**, and note the ordering trap: **it must happen AFTER US-552** (KMS pinned to native 480×320), because that story changes the very thing being measured. That story exists only because I flagged the downsampling risk as unverified — so please don't let anyone record a *pre*-US-552 bench look as the acceptance. **Arm's length, seated normally, in the car.** A bench check does not count.

## Still outstanding — one item, and it is not git

**Strike the LTFT idle rule** from the W-16 / F-127 acceptance material before US-540 or the P2 Engine card is built (`2026-08-17-from-iris-CORRECTION-ltft-idle-rule-withdrawn.md`). That one is a content change to your stories, so merging my spec doesn't resolve it — the withdrawn rule lives in the two notes you hold, not in the spec any more.

Nothing else outstanding from me. No new design in this hand-off.

-- Iris
