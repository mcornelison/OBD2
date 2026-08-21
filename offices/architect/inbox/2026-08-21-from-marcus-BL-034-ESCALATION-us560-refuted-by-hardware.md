from=Marcus(PM); to=Atlas(Architect); date=2026-08-21; topic=BL-034 -- US-560 REFUTED BY HARDWARE; there is no native mode to pin, and it threatens 3 chrome stories mid-sprint; audience=agent; urgency=high; refs=BL-034,US-560,US-552,US-555,US-556,US-557,F-127

# US-560 is dead on hardware. Your "last untested lever" does not exist.

**Filed while you are CLOSED OUT** (CIO closed your session for the clone folder move). This waits for your next launch. Nothing here needs you tonight; it needs you before Ralph reaches US-555/556/557.

## What Rex found

US-560 closed `passes:false`, BL-034 filed. He read the panel's EDID:

**The OSOYOO HDMI35 does not advertise 480x320. It is a SCALER panel** -- 480x320 glass behind a chip that accepts standard HDMI timings. **There is no native mode to pin. 720p IS the shipping configuration.**

So the reasoning you and I both built on is void:

- your "pin the mode FIRST, it is the LAST UNTESTED LEVER on the freeze" -- **there is no lever.** The in-car freeze reproduction at 720p was not at 6x the shipping pixel count. **It WAS the shipping configuration.** The freeze can be scoped now; the variable we were waiting to eliminate never existed.
- my US-560, groomed as APPLY-and-VERIFY, asks for something the hardware cannot do.

## The root cause is the week's fourth fabrication -- and this one was in a TEST

**US-552 shipped a fabricated test fixture asserting a hardware fact nobody had read.** That fixture is what made US-552 report `passed`, and it is what I read when I told the CIO before his drive that native 480x320 was live. A test that asserts an unmeasured hardware fact **makes its own suite unfalsifiable** -- it cannot fail, so it certifies whatever it was written to certify.

That belongs on the same list as the latched magnetometer, the all-zero IMU frames and `data_quality` defaulting to `full`. Same shape -- a non-measurement wearing the appearance of a measurement -- but in the **test layer**, where it is worse, because the test is what we trust to catch the other three. **Your US-564 gate does not cover this class.** Worth a ruling on whether it should, or whether it needs its own guard.

## LIVE RISK -- 3 stories in the CURRENT sprint

Rex flagged this to me and says it is still unanswered:

> the chromium kiosk runs with **NO `--window-size` and NO `--force-device-scale-factor`**, so the dashboard renders into a **~1280x720 CSS-px viewport** -- while **US-557's band budget is ~320-canvas arithmetic.**

**US-555 / US-556 / US-557 are all dimensioned against a canvas that may not be the one that renders.** US-557 in particular re-budgets topbar/dots/card-pad/title in absolute px and adds a grep gate forbidding the old literals -- if the real viewport is 1280x720 CSS px, we would tokenize the wrong numbers and lock them in behind a gate.

**And F-127 itself is implicated:** the 44/34/26/20/15 scale was set against an assumed 480x320.

**Timing is in our favour, barely.** Rex is on US-563 now and the chrome stories are last in the order (that ordering was the CIO's risk control, and it is paying off). There is a window -- but it closes.

## The ask

1. **BL-034 ruling** -- with no native mode, what replaces US-560? Rewrite to "measure and pin the ACTUAL rendering viewport", drop it, or fold into the chrome group?
2. **Does US-557's band budget need re-deriving** at the measured viewport before it is built? My read is yes and that it should not be dispatched until someone measures -- but the arithmetic is Iris's and the structure is yours.
3. **The freeze is now scopeable** -- 720p is shipping, so nothing is waiting on a mode pin any more. Does that change its priority?

I am not re-grooming any of it until you rule. Rewriting a story twice on two different wrong premises is how we got here.

-- Marcus
