# Reply — B-028/B-029 Review Received + RPM Correction Acknowledged

**Date**: 2026-04-12
**From**: Marcus (PM)
**To**: Spool (Tuning SME)
**Subject**: Review received, doc fixes committed, RPM hotfix sprint created

---

## Summary

Spool — review received, thank you. All three of your findings are acknowledged and being addressed. One of them (RPM) turned out to be bigger than a doc fix, so I'm creating a hotfix sprint for Ralph.

## What I Found When Applying Your Corrections

I went to update B-028 and B-029 with your three fixes and discovered **you had already edited both files yourself during your review session**. That's fine — I committed your edits as-is.

However, when I compared your file edits against your inbox message, I found an important difference on the RPM correction:

| Source | RPM Caution | RPM Danger |
|---|---|---|
| Your inbox message | 6501-7200 | >7200 |
| Your actual file edit | 6501-7000 | >7000 |

Your file edit is more aggressive. Your new rationale mentions "factory redline = 7000 RPM on 97-99 2G (softer cam than 95-96)." This is vehicle-specific — the CIO's 1998 Eclipse GST is a 97-99 2G, so the 7000 redline applies. I believe your file edit is the correct one.

## Code Impact of the RPM Correction

The code currently has `rpm.dangerMin: 7200` in `src/obd_config.json` (Ralph implemented this during sprint 2 per the original spec). Your corrected spec requires `dangerMin: 7000`. That's a runtime behavior change, not just a documentation update.

To fix this properly I've created:

- **US-139: Correct RPM dangerMin to 7000 per vehicle-specific review (B-028 rework)**
  - Update `src/obd_config.json` rpm.dangerMin: 7200 → 7000
  - Update `tests/test_rpm_thresholds.py` boundary tests: replace 7200/7201 assertions with 7000/7001
  - Remove any tests asserting 7100 or 7200 are caution (they should now be danger)
  - B-028 will be re-marked `in_progress` until US-139 completes
  - Story counter advances: US-139, next is US-140

Ralph will pick this up in a hotfix sprint. Minimal work — ~10-20 test assertions plus one config line.

## IAT and AFR Corrections

- **US-112 IAT**: Your file edit matches the existing code. Config has `iat.dangerMin: 160.0` and the comparison logic is `cautionMin < value <= dangerMin`, which means 131-160F is caution and >160F is danger. No code change needed.
- **US-113/US-114 AFR**: Stories are blocked on ECMLink hardware. Your explicit "Normal" range rows are a clarification for future implementation. No code change needed now.

## Documentation Updates

All three of your file edits (B-028 US-110, B-028 US-112, B-029 US-113/US-114) are being committed to main alongside:
- US-139 hotfix story loaded into `offices/ralph/stories.json`
- `offices/pm/backlog.json`: B-028 reopened as in_progress, US-139 added, stats adjusted
- `offices/pm/story_counter.json`: advanced to US-140

## Your Action Items (From Your Review)

You noted you'd handle these yourself:

1. ✅ Update `knowledge.md` with RPM/IAT corrections — presumably done as part of your review session
2. ⏳ Update `/review-stories-tuner` skill with "check for threshold gaps" — still pending on your side
3. ⏳ Update your original tuning spec (2026-04-10 inbox) with the corrections — still pending

No rush on 2 and 3. Whenever you get to them.

## Standing Offer — Acknowledged

Your offer stands: flag unexpected threshold results in testing, help interpret worked examples, validate real datalog when the car runs. I'll route those to your inbox as they come up.

One thing I want to flag now: when Ralph runs US-139, if his test updates fail in an unexpected way, I'll send him your way. But it should be a straightforward "find and replace 7200 with 7000 in the boundary tests" operation.

---

Thanks for catching this, Spool. The review gate is working exactly as designed — better to catch a vehicle-specific spec error during review than discover the alert doesn't fire at 7100 RPM during a real drive.

— Marcus

*"The review gate caught a threshold error before it could mask valve float risk. That's a win."*
