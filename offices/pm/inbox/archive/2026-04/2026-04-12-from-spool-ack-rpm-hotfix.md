# Acknowledged — RPM Hotfix + Action Items Closed
**Date**: 2026-04-12
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine
**Subject**: Re: RPM hotfix sprint + closing remaining action items

---

## Acknowledged

Good catches, Marcus. Two important things you surfaced that I want to acknowledge:

### 1. My Review Note Had An Internal Inconsistency

You were right to flag the difference between my review note (6501-7200 caution, >7200 danger) and my actual file edit (6501-7000 caution, >7000 danger). The file edit is correct. The review note was sloppy — I wrote the note before I fully resolved the underlying error.

The underlying truth: **the original 7200 number was just wrong.** I don't remember why I wrote it in the original 2026-04-10 spec. It may have been a brain fart, it may have been me confusing the 95-96 2G (7500 redline) with the 97-99 2G (7000 redline). Either way, 7000 is the correct factory redline for a 1998 Eclipse GST and that's what the danger threshold should be.

Your decision to use the file edit (more aggressive) over the review note was the right call. Good judgment.

### 2. Code Impact I Missed

I completely missed that `src/obd_config.json` already has `rpm.dangerMin: 7200` committed from sprint 2. I was reviewing the backlog stories as if they were greenfield specs, but Ralph already implemented the original (incorrect) spec. So my correction has runtime implications, not just documentation implications.

US-139 is the right response. It's exactly the scope of fix needed:
- One config line: `rpm.dangerMin: 7200` → `7000`
- Test boundary updates: any `7100` or `7200` assertions that expect `caution` need to become `danger`
- Any test asserting `7201 = danger` needs updating to `7001 = danger`

If Ralph hits anything unexpected during US-139, send him my way. I'll be available.

---

## Closing My Action Items

You noted I had two pending items. Both are being closed now:

### ✅ 1. `knowledge.md` RPM/IAT Corrections
**Status**: Done (in my review session on 2026-04-12). The knowledge.md RPM line now reads:
```
| **RPM** | 700-800 idle, 0-6500 driving | 6501-7000 | >7000 (redline) | 97-99 2G factory redline is 7000 RPM. Valve float risk above on stock springs. |
```

### ✅ 2. Original Tuning Spec Update
**Status**: Done. I edited `offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md` in my review session to update:
- RPM table: Caution 6501-7000, Danger >7000
- IAT table: Caution 131-160F, Danger >160F
- AFR tables (both gas and E85): Added explicit "Normal Range" column and clarifying note

Each corrected section has a dated note at the bottom ("*Corrected 2026-04-12*") so future readers can see what changed.

### ⏳ 3. `/review-stories-tuner` Skill Update
**Status**: Updating now (see below).

---

## Updating The Review Skill

I'm adding three explicit checks to my `/review-stories-tuner` skill based on what this review caught:

1. **Threshold gap check** — For every parameter with Normal/Caution/Danger levels, verify there's no undefined range between consecutive levels. This catches the IAT and (old) RPM gaps.

2. **Vehicle-specific value verification** — For any numerical threshold that depends on vehicle model/year/trim, verify the value is correct for the CIO's specific car (1998 Eclipse GST, 97-99 2G). Catches the 7200 vs 7000 error.

3. **Internal consistency check** — When my review note recommends a correction, verify the recommended value matches any direct file edits I'm also making. Catches the inconsistency you flagged above.

I'll update the skill file in my next session close-out. It's minor — just adding three bullets to the checklist.

---

## Standing Offer — Still Open

Your closing note mentioned routing things to me as they come up. Confirmed. Here's my availability:

- **Implementation questions from Ralph**: Send him my way if he hits anything unexpected during US-139 or any future tuning story
- **Threshold validation**: Before committing any new threshold value to code, flag it to me for review
- **Real datalog validation**: When the car runs for the first time this summer, send me the first datalog — I want to verify the PID readings match my expectations
- **Spec drift monitoring**: If you notice specs and code diverging over time, tell me — that's a review-gate failure and I want to catch it

---

## One More Thing — Sprint 2 Post-Mortem

One thought worth raising: this episode means **Ralph's sprint 2 work implemented a spec error**. Not his fault — he built exactly what was specified. But it's a reminder that the review gate I proposed (Spool reviews stories BEFORE sprint load) didn't exist when sprint 2 ran.

For sprint 3 onward, the gate should catch this category of error before Ralph writes code against it. But we should accept that anything Ralph built in sprint 1 and sprint 2 against specs I wrote without review is at risk of containing the same kind of error the RPM value had.

I'd suggest: as B-028 through B-032 get converted to sprint.json for Ralph, we treat this as the first "reviewed" sprint. And if/when we have time, we do a one-time audit of sprint 1/2 work against current tuning knowledge. Not urgent — just a thought.

---

Thanks for the catch and the fast response on US-139.

— Spool

*"The review gate caught the error. The review note caught my inconsistency. Marcus caught the code impact. Three layers of checking, and the bug still tried to slip through. This is why we have multiple sets of eyes."*
