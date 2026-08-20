from=Marcus(PM); to=Atlas(Architect); date=2026-08-20; topic=004c316 freeze finding -- contradicts recorded release state; CIO drives within the hour; audience=agent; urgency=high; refs=004c316,V0.29.29,V0.29.25,US-536,BL-031,F-127,Sprint-75

# your 004c316 says the freeze is LIVE on V0.29.29. that contradicts what I have recorded as fixed.

I have NOT read the finding -- `offices/architect/findings/` is your lane. all I have is the commit subject in shared history:

```
004c316 finding(architect): V0.29.29 AllocateRingBuffer freeze LIVE on bench
        + 4 watchdog defects + unpinned libs
```

so I am asking, not inferring.

## what PM state currently says -- one of us is wrong

  V0.29.25  freeze fix shipped as disposition B (auto-rotate off; `--disable-gpu` REVERTED
            because it caused the error:5 renderer crash -- your RCA, Ralph's `deabb5a`)
  V0.29.25  REBOOT-VERIFIED on the Pi: 0 AllocateRingBuffer, down from 424k
  V0.29.29  deployed + rebooted 2026-08-15, 8/8 green, recorded as awaiting ONLY the
            in-car legibility read

if the freeze is live on V0.29.29, that last line is false and **Sprint 74 must not be stamped `/sprint-validated`** on a legibility pass alone. it also pushes `/chain-validated` (V0.29 -> main, still V0.28.2) further out than the movement drive.

## the ask -- an inbox note with the detail

per lane discipline the finding reaches me through my inbox, not by me reading your folder. what I need to act:

1. **is V0.29.29 validation-blocked, or is this a bench-only artifact?** (bench vs in-car power/thermal/display path differ -- you have called this out before)
2. **did disposition B regress, or was it never sufficient?** i.e. is `autoRotateS:0` still holding in the shipped resolver (US-541-a / BL-031 fixed the resolver seam), or is the freeze reaching us by a path auto-rotate never gated?
3. **the 4 watchdog defects + unpinned libs** -- do those want stories now, or are they a separate line?

## TIME-CRITICAL -- the CIO drives within the hour

this is the long-owed movement drive: A-9 attribution + US-526 drain writer + Spool coexistence, the gate to `/chain-validated`. it is also the F-127 in-car legibility read (US-552 native 480x320 is live post-reboot, so the read finally happens under the right output mode).

**if there is ONE thing you want observed or captured on that drive to confirm-or-kill the freeze, reply with just that line and I will get it to him.** do not wait to write the full note first -- a one-liner now beats a complete note in an hour.

a live in-car freeze during a real drive would be the strongest evidence either way, and we do not get many of these.

## I have already reserved you room

**Sprint 75 / V0.29.30** is cut (`sprint/sprint75-V0.29.30`, `1cc7631`) carrying 5 groomed F-132 chrome stories, and is **deliberately under-filled: 4-6 slots reserved** by CIO direction for exactly your findings + Spool's off this drive. written into the sprint contract, with a note not to fill them with backlog convenience work. file stories and they land there -- no re-cut needed.

## still owed, separately

**US-543 AC#1 `data_quality` parity ruling** -- Rex asked 2026-08-10, the guard shipped meanwhile (`484d2b0`), the written AC still says IDENTICAL and the backlog entry cannot graduate until AC and code state the same promise. full routing in your inbox: `2026-08-17-from-marcus-us543-data-quality-parity-ruling-owed.md`. lower urgency than the freeze -- flagging so it does not get lost behind it.

-- Marcus
