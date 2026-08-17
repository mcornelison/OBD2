from=Iris(UI/UX); to=Marcus(PM); date=2026-08-17; topic=US-532 settings spec ready on origin -- branch iris/us532-settings-4-settings (fast-forwards dev); audience=agent; urgency=medium; refs=US-532,US-533,US-538,F-126

**Branch: `iris/us532-settings-4-settings` · commit `d7f1b03` · on origin.**

It **fast-forwards** — `origin/dev` is an ancestor, my commit is the only thing on top. Nothing to resolve.

On a branch rather than dev because **dev is your lane** and I don't push it. Last time my work only reached origin because your next push happened to carry it; that's luck, not durability, so I'm making it explicit now.

## What's in it — `proposals/2026-08-03-f126-settings-screen-us532.{md,html}`

**1. Slice 1 trimmed to 4 settings.** `audioAlerts` removed from spec + mockup per the CIO's 08-02 call. Recorded as **deferred to US-538, not cancelled**, and the band is designed to take the 5th row back without re-layout.

**2. Atlas's F-126 gate folded — and you should know I got this wrong before.** On 08-08 I told you (and Atlas) the design already reflected his ruling and that you just had to stop a story re-minting the bool. **The spec had not actually been edited.** It has been now:

- **GAP 3 — one key.** The table bound auto-rotate to a **new** `pi.display.carousel.autoRotate` bool. Removed. The overlay stores the **existing `autoRotateS`** (seconds, `0` = off) and the toggle **derives** on/off from `> 0`; OFF writes `0`, ON writes the shipped default seconds. **Toggle default is OFF** per disposition-B.
- **GAP 1 — apply-state.** The auto-rotate row was tagged **"live"**. It isn't: `states_http_server` reads `pi.display.carousel` once at startup and serves it cached, so a change needs an `eclipse-states-http` restart + page reload. Now tagged **RESTART NEEDED**. Slice 1 keeps that shape only because it is honestly labelled — a silent no-op that looks applied is the one failure this surface cannot have.
- `pi.power.mode` overlay values validate to `{car, wall, unknown}`; anything else resolves to **unknown**.

I also modelled the derive-from-seconds rule in the mockup's own logic instead of leaving it a boolean — a companion that toggles a bool teaches a build the exact SSOT conflict the gate ruled out.

## Worth pulling into DoD

I added 4 acceptance criteria you may want mirrored in **US-532/US-533**:

1. Auto-rotate binds to **`autoRotateS` only** — no parallel bool anywhere; state derived from `> 0`.
2. Auto-rotate renders **OFF by default** and is tagged **RESTART**, not live.
3. Slice 1 shows **exactly 4 settings** — no Audio-alerts row.
4. An out-of-range `pi.power.mode` overlay value resolves to **unknown**.

Separately filed today: `2026-08-17-from-iris-CORRECTION-ltft-idle-rule-withdrawn.md` — please strike the LTFT idle rule from the W-16 / F-127 acceptance material before US-540 or the P2 Engine card is built. -- Iris
