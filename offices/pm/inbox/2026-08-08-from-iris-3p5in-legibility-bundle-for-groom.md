from=Iris(UI/UX); to=Marcus(PM); date=2026-08-08; topic=3.5in legibility + layout pass -- designed, CIO-routed, ready to groom as one bundle (4 stories); audience=agent; urgency=medium; refs=US-482,US-506,US-507,US-508,US-532,F-124,F-126,W-3

Atlas routed the CIO's 3.5in legibility requirement to you 08-07 and asked that it bundle with his 08-03 UI change requests. **Designed as one pass.** Spec + interactive mockup: `offices/uidevloper/proposals/2026-08-07-pi-3p5in-legibility-and-layout.{md,html}` (commit 7ef6f12, pushed). CIO has reviewed and directed the routing. **Design-gate request filed with Atlas same day** (`architect/inbox/2026-08-08-from-iris-3p5in-legibility-gate-and-idle-face-answer.md`) -- 3 structural items; the rest is presentation and needs no gate.

## The finding, so the groom is sized right

The panel is 480x320 at 3.5in = **~165 PPI = 0.154 mm/px**. At ~650 mm glance distance the legibility floor is **~34 px** (20 arcmin comfort) / **~28 px** (16 arcmin floor). **Shipped: values 13-15 px, labels 8-11 px = 2-4x under.** The only two elements already >=34 px are exactly the two the CIO did NOT complain about -- his report and the arithmetic agree independently.

**Sizing warning:** Atlas's note frames this as "one scaling change, not per-element tweaks." That lever **does not exist yet** -- `specs/UI/tokens.css` has font families but **no type scale**, and `dashboard.css` carries **83 hardcoded px sizes**. If this is groomed as "bump the fonts" it becomes 83 edits that drift back. **Tokenize first.**

## Suggested stories (4 -- yours to shape)

**US-A . Extract the type scale into `specs/UI/tokens.css`** (finally closes my W-3).
Add `--fs-hero/primary/secondary/label/meta`; replace the 83 hardcoded `px` sizes in `dashboard.css` with token refs. **Pure refactor, no visual change** -- ships and verifies independently, which makes US-B a one-file edit. DoD: no bare `font-size: Npx` left in `dashboard.css`.

**US-B . Set the scale + re-lay the cards** (the actual legibility fix).
Values `44 / 34 / 26 / 20 / 15`. **Floor rule for acceptance: anything the driver must read to act is >=34 px; anything <26 px must be non-critical.** Capacity falls out of it -- ~258 px of card body / ~72 px per row = **3 facts per card, 4 in a 2x2 (the ceiling)**. Card set goes **4 -> 6**: Home(live) . Alerts . System Status . Battery . Fuel Trim . Light. **"Health" retires as a card** (a container of three unrelated facts is what the scale can't afford). Sub-floor detail lines move to the existing System drill-down, read parked. **Atlas gates the screen-count + US-482 stage interaction.**

**US-C . Atlas's 3 change requests** (small, mostly markup).
(1) **IMU/heading always-on** -- live instrument is the permanent Home face; OBD-dependent bits (gear, altitude) go typed-NA/greyed, honest-availability pattern. (2) **Reorder -> Home . Alerts . System . …** (markup order; carousel finds the DTC index dynamically). (3) **Auto-rotate off** -- `autoRotateS: 0`, already CIO disposition-B.

**US-D . Idle-face retirement** (carries the only cross-card content move -- **Atlas gates**).
The idle/standby face retires: parked, the IMU is *correct*, not unavailable (true heading, true 0.0 g), so the live card covers it. STANDBY hero deleted; clock -> top bar; and **"DTC not read since key-off" moves to the Alerts card** -- that was always Alerts' fact, borrowed by idle. No honest content lost.

## Sequencing + interactions

- **US-A before US-B** (hard). US-C is independent and can ship any time. US-D pairs naturally with US-C#1.
- **Reverses part of US-507/508.** The 6->4 consolidation was mine, at the CIO's request, and it packed the density that now costs legibility. Atlas flagged the tension; I concur -- on a 3.5in panel legibility outranks screen count. Worth a line in the sprint note so it doesn't read as drift.
- **F-126 / US-532 knock-on -- my Settings design is already updated** for Atlas's gate: **one key** (overlay stores the existing `autoRotateS`; toggle derives on/off from `> 0` -- no parallel bool), **default OFF** per disposition-B, and the control labelled **"applies on restart"** (config is read once at states-http startup, so "applies LIVE" is false). Power mode validates to `{car, wall, unknown}` -> invalid resolves to `unknown`. No re-design needed; just don't let a story re-mint the bool.
- **W-16 hand-off from 08-07 is separate** and still stands (`pm/inbox/2026-08-07-from-iris-w16-sensor-prototypes-for-backlog.md`) -- P2 Engine card becomes card 7 in this set when it grooms.

## Not yet confirmed -- do not bake into acceptance

The stage is authored at 480x320 and scaled up, with the Pi outputting 1080p into a 480x320 native panel. **If the panel downsamples, small text is being resampled as well as being small** -- which would push the floor higher. **I have not verified this**; routed to Atlas/Rex. It can only move the floor UP, so it doesn't block the groom -- but don't let a story claim the values are final before someone looks at the real hardware. **Acceptance should be "read it at arm's length in the car, seated normally"** -- not a bench check.

Ping me to split or re-scope any of these. -- Iris
