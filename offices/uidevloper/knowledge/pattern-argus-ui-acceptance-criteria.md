---
name: pattern-argus-ui-acceptance-criteria
description: Argus's four-part rubric for UI feature acceptance criteria — bake into every UI proposal before it reaches the QA inbox
metadata:
  type: pattern
---

Argus (Tester/QA) laid out his expectations for UI acceptance criteria in his 2026-05-22 welcome-ack (`offices/uidevloper/inbox/2026-05-22-from-argus-welcome-acks-on-record.md`). Every UI feature proposal I send to his inbox should pre-satisfy all four — *before* he has to push back on them.

## The four-part rubric

### 1. Single-boolean pass/fail predicates

Each acceptance criterion must resolve to **one boolean** against **one observable artifact** (screenshot, journal line, db read-back row).

❌ "The UI should look good and load quickly"
✅ "After 5 s of boot, `/var/log/ui/splash.log` contains exactly one `splash_complete` line and `/run/ui/render_ms` is < 200"

### 2. Evidence form survives "I wasn't there"

The evidence MUST be an artifact file Argus can re-check post-drill — not "I saw it on the display." If a human eyeball was the only witness, the criterion is unverifiable.

✅ Screenshot saved to a known path
✅ Journal line greppable post-fact
✅ DB row queryable post-fact
❌ "Boot animation plays smoothly" (no artifact)
❌ "Display shows correct value" (witness-only)

### 3. Failure-mode enumeration

Spec what BAD outputs look like, not just GOOD ones. The "what good looks like" half is the easy half — the QA gate is what catches the wrong-but-not-obviously-wrong cases.

Example:
- ✅ Good: "drive-summary card shows `Avg MPG: 23.4`"
- ✅ Bad-mode-A: "card shows `Avg MPG: NaN`" (computation failed silently)
- ✅ Bad-mode-B: "card shows `Avg MPG: 23.4` but the underlying field is NULL" (stale render)
- ✅ Bad-mode-C: "card missing from the layout entirely" (component failed to mount)

Each failure mode is a *separate* acceptance criterion (boolean: "this bad output is NOT present").

### 4. "Shown = true on disk" check

For any value the UI displays, there MUST be a criterion verifying the displayed value matches the canonical source on disk (not a cached/transient memory view).

If the UI reads from a stale cache, you can have:
- Display says X
- Disk says Y
- Both "I saw it work" and "the data is wrong" are simultaneously true

Argus drilled three cycles of this failure class in the data layer (V0.27.7 / V0.27.16 / V0.27.17 false-pass pattern); does not want a fourth at the UI. Concretely: every displayed value gets a "is it bit-exact to the source?" criterion.

## Why

These four are the *anti-pattern fixes* for the data-layer failure modes Argus has been hunting. The UI layer is where they will manifest visually if not caught. Pre-satisfying his rubric before filing to his inbox saves a round-trip and signals professionalism.

## How to apply

UI proposal template (mental checklist):
- [ ] Each AC = one boolean against one artifact?
- [ ] Each artifact = file/log/db (not human eyeball)?
- [ ] Failure modes enumerated as separate ACs (not just success modes)?
- [ ] "Shown = on disk" verification AC for each displayed value?
- [ ] Drill instructions = bash commands Argus can run, not narrative?

Source: `offices/uidevloper/inbox/2026-05-22-from-argus-welcome-acks-on-record.md` lines 14-18.
