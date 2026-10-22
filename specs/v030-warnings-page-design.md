# V0.30 Warnings page + top-bar warning icon — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 (brainstorm 2026-10-12/13; **reworked 2026-10-13 for R31**) · **Status:** CIO-APPROVED design; provider in S107, page in S108. **§4.4 rewritten: the CIO kept the full-screen takeover (R31, Marcus 2026-10-13 14:41). My no-takeover design (WN-3) is superseded. Scope ruled 2026-10-14: only a live coolant red takes over (§4.4, new §4.4a).** **S106 brief folded 2026-10-18 (UIDEV-005):** the key-on CODE ALERT (§4.4b, CIO put it in S106), SYSTEM/DATA not in V0.30 (Atlas §5), the empty state prints only what was assessed (§4.3), tokens ruled, and §5–§7 rewritten as the build contract. Brief: `pm/inbox/2026-10-18-from-iris-S106-brief-Warnings-US-897-898-899-specs-fields-ACs-gates-gaps.md`. **S108 folds 2026-10-19 (UIDEV-006):** my U1–U12 answers, my S108 PRD review + row-ages ruling, Atlas G3/G4/G6/G7 (10-18) and his S108 review G1–G3, Spool's US-754 rows (P0430 is not this car) and UNRATED sentence. The page is built in S108 (US-898-a/b1/b2/c, US-899-a1/a2/b). **Where this spec and the OEM mockup differ, the spec wins** (the mockup predates these folds; §10 lists the differences).
**Mockup (build from this):** `specs/v030-warnings-page-oem.html` (repo copy, UIDEV-005) → https://claude.ai/artifact/KKE2HvXZmUZJDPFP6SrRhk (OEM skin, v2, 2026-10-18: PULL OVER + code alert + every §7 fixture). *(Superseded: the 2026-10-12 layout mockup https://claude.ai/artifact/1hZxFmhcUM8rY5onGu8eXU, which set layout A, scrolling.)*
**DoD lines served:** 9 (warnings: top-bar icon on every page + own page), 8, 12 (carries US-754, US-758; ARCH-062)
**Builds on:** W-12 unified alert layer (Atlas ruling 2026-06-19: one arbiter-owned `alerts` view-state, an aggregator over providers; tier → live > stored → newest). Spool tiers: `specs/grounded-knowledge.md` DTC severity row + `tuner/dtc-display-clear-safety-advisory.md`.
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose
**Everything that needs attention, ranked, in one place**, with an icon on every page so nothing can hide on a page you aren't looking at.

## 2. Decisions locked (CIO)

| # | Decision | CIO choice |
|---|---|---|
| WN-1 | Sources | **Trouble codes · live engine protection · system issues · data-capture stall.** V0.30 builds CODE + ENGINE only; SYSTEM and DATA are declared `assessed:false` until their producers exist (Atlas 2026-10-14 §5; §4.1). |
| WN-2 | Icon | **4 states + count**: none / not checked / WATCH / STOP |
| WN-3 | Full-screen takeover | ~~None (icon + page only)~~ **SUPERSEDED by R31 (CIO, asked directly 2026-10-13): an active red TAKES OVER the screen. Scope ruled 2026-10-14: LIVE COOLANT red only; RPM/battery red = WATCH; stored codes never** (§4.4). |
| WN-4 | STOP signalling | **Takeover (§4.4) + pulsing red icon.** The one-time jump to Warnings is **dropped**: the takeover already owns the screen, so a jump underneath it does nothing. |
| WN-5 | Live engine protection | **In** (CIO first excluded it, then restored it once shown the gap: an overheat would otherwise show only on the driving page) |
| WN-6 | Clear-code flow | **Keep as shipped** (Mode 04, gated) |
| WN-7 | Order | **One list by severity** |
| WN-8 | Acknowledge | **Stops the pulse; the entry stays until its cause clears.** Held by the provider for the current boot only (Atlas §3), so each key-on re-arms. |
| WN-10 | Stored codes at key-on | **A dismissable CODE ALERT once per key-on** (CIO to Atlas 2026-10-14; into S106, CIO 2026-10-18). §4.4b. |
| WN-9 | Layout | **A · Ranked list, showing ALL entries; scrolling allowed** |

## 3. Layout (480 × 320; body 270 = 320 − 34 bar − 16 dots)

```
┌──────────────────────────────────────────────┐ top bar: BT ⇅ [wifi] ▲3 (warning icon, every page)
│ 3 ACTIVE                        codes read 6:42│ ~40  --fs-primary
├──────────────────────────────────────────────┤
│ [STOP ] ENGINE OVERHEATING  234 °F    just now │ ≥ 48
│         Stop safely, engine off. Do not open…  │
│ [WATCH] CHARGING FAULT  11.8 V       2 min ago │
│         Head somewhere safe. Turn off access…  │
│ [WATCH] EGR FLOW (P0400)           41 days ago │
│         Drive gently. Get it diagnosed.        │
│ [MINOR] EVAP PURGE (P0443)         …           │ ▓ scrollbar when more
│ ↓ n more below                                 │
└──────────────────────────────────────────────┘
```

| Element | Tier | Note |
|---|---|---|
| Header | `--fs-primary` | `n ACTIVE` / `NONE` (142.4 px) / `NOT CHECKED` (amber, 352.7 px) / `--` (no data, §4.3) + `codes read h:mm` or `codes not read yet`, `--fs-meta` (12-hour, no AM/PM: the one clock rule, the `fmtTimeOfDay` split) |
| Chip | `--fs-meta` | STOP `--critical-red`, ink `#fff` (the existing STOP copy colour, 4.98) · WATCH `--amber-warn`, ink `var(--bg)` (12.4) · MINOR `--green-ok`, ink `var(--bg)` (8.73) · UNRATED `--neutral-chip-bg` (#2a2f37, tokens.css SSOT; the dashboard.css:185 mirror STAYS, Atlas G6), ink `--text-primary` (11.94). **No new tokens** (Atlas 2026-10-16, contrast MEASURED). |
| Title | `--fs-label` mono | the provider's `title` (a code row reads `EGR FLOW (P0400)`) + value and unit through `displayUnits` (°F for coolant). Stale: `last.value` + `last reading n s ago` (§4.6) |
| Sentence | `--fs-meta` mono | the provider's `sentence` as **plain text** (US-758) |
| Age | `--fs-meta` mono, right | **`agoText(now, firstSeenTs)` unchanged**: `just now` / `n min ago` / `n h ago` / `n days ago` / `age unknown`; `cleared` for an `active:false` row. **No `code ·` / `engine ·` prefix** (the title already names the source). Worst row: `EVAP PURGE (P0443)` 216.7 + chip ~60 + `999 days ago` 108.4 + 2 × 8 gaps ≈ 401 of 448 px; with a prefix ≈ 455 px, which clips |

Entries ≥ 48 px tall, never `.tile` (the fact-ceiling test). **All entries render; the list scrolls** with a visible scrollbar (styled through scoped custom properties) and a mono `↓ n more below` cue (no silent clip). **n is counted from layout at runtime:** the rows whose bottom edge is below the list's visible bottom. The pure function (48 px rows in 270 px minus the MEASURED header and cue heights) is only the no-layout fallback the harness tests, and it never reports fewer than the layout would; 7 entries ⇒ `↓ 3 more below` (270 − ~40 − ~20 = 210 ⇒ 4 visible). A pure function alone can under-count once a row wraps, which is the dishonest direction. Ranking means the most severe are always above the fold, so **nothing requires touch while driving** (R5).

**Fonts on this page:** Michroma (`--font-display`) is **UPPER-CASE only** (the subset is A-Z, 0-9, space and hyphen). It carries `NONE`, `NO WARNINGS`, `NOT CHECKED`, `NOT CHECKED YET`, `n ACTIVE`, `TROUBLE CODES`, `DISMISS` and the chips. Everything with lower case or a symbol (`?`, `▲`, `△`, `:`, `+`, `↓`, `·`, `°`) is `--font-mono`, including every sentence, reason and notice.

## 4. Behaviour

### 4.1 Sources and ranking
| Source | What becomes an entry | Tier |
|---|---|---|
| **CODE** | stored/pending DTCs | Spool's table; **unknown ⇒ UNRATED, never a guessed tier** (US-754). Rated (Spool 2026-10-18, rows in US-754, S106): **P0400 WATCH** `EGR FLOW (P0400)` / `Drive gently. Get it diagnosed.` · **P0443 MINOR** `EVAP PURGE (P0443)` / `Emissions only. Safe to drive.` P1xxx titles follow the same `<NAME> (<code>)` form (Spool S2, 2026-10-19). **P0430 has NO row** (corrected 2026-10-18; my 10-13 "P0430 WATCH" is withdrawn): bank-2 codes (P0430, P0150–P0167, P0174/P0175) cannot set on this inline four. The only P0430 in `dtc_log` is drive 33, a cross-logged Ford Explorer. Such codes are wrong-vehicle data and render **UNRATED, never a tier**; the drive-33 rows must not appear on the page (provider VCs). **UNRATED sentence** (Spool 2026-10-19, provider-owned): `Severity unknown. Get it diagnosed.` (35 characters = 316.1 px at `--fs-meta`, inside the ~380 px sentence column, so Spool's fallback `Not rated. Get it diagnosed.` is not needed). UNRATED counts above MINOR for the clear gate. A new UNRATED code on the car is Spool's trigger to rate it; there is no speculative P0 table. |
| **ENGINE** (live) | coolant, battery voltage, RPM over-rev, intake air in a band, **with the dwell rules** | **STOP: live coolant red only.** Battery red and RPM red = **WATCH** (§4.4a). Intake air never above WATCH. |
| **SYSTEM** | ⏸ **not in V0.30.** `system-status` has no `verdict` yet (US-877 not built), so the provider publishes `sources.system.assessed:false`. When built: whatever the System verdict counts (System spec §4.1) | WATCH |
| **DATA** | ⏸ **not in V0.30.** The engine-running stall predicate (US-735) is banked (CIO R33), so a stall can't be told from engine-off; `sources.data.assessed:false`. When built: capture stalled while the engine runs, from `capture-health.feeds` | WATCH. Predicate ratified (Spool 2026-09-21): accel_z σ > 0.10 for **N = 7** consecutive 10 s buckets. |

Order: **tier (STOP > WATCH > MINOR > UNRATED) → live before stored → newest first** (Atlas 06-19; Spool-confirmed). The **arbiter** orders; the page renders the order it is given.

### 4.2 Top-bar icon (every page)
| State | Condition | Look (mono text in a fixed 3-character slot) |
|---|---|---|
| none | checked this session, list empty | `△` (U+25B3) in `--text-tertiary`. The slot is never empty: the icon is never hidden |
| **not checked** | codes **not read this session** (ARCH-062) | amber `?`; **never looks like "all clear"** |
| WATCH | highest active is WATCH/MINOR/UNRATED | amber `▲` + count, e.g. `▲2`. **RULED (Atlas G7):** the provider maps MINOR-/UNRATED-only to `watch`; counted means amber (CIO 2026-10-16), and "not rated" is never phrased as safe |
| STOP | highest active is STOP | red `▲` + count; **pulses until acknowledged** |
| *(no data)* | `states/alerts` missing, unreadable, or still loading | **`--` in `--text-tertiary`**, no triangle, no pulse; still tappable. **Never `none`:** `none` is the provider's claim that the codes were read and nothing is active, and with no payload that claim is false (S108 review) |

- Count above 99 shows `▲99`.
- `prefers-reduced-motion` ⇒ no pulse; a steady red outline instead.
- **The provider computes the state** (`states/alerts.icon {state: none|not_checked|watch|stop, count, pulse}`); the page renders it through a pure `alertIconView(alerts)` and compares nothing. An active STOP or WATCH outranks `?`.
- **Tap:** opens ALERTS. A control with a transparent 40 px `::after` hit box (the `#menu-btn` pattern). **Allowed while moving:** it only navigates, which a swipe already does, so R5 (nothing may *require* touch while moving) holds. Unlike the kebab, the icon is never hidden.
- **Room in the top bar (U1 + S108 review).** The left cluster had no room for a fifth glyph, so WiFi gives it up:
  - `#glyph-wifi` is redrawn as an inline SVG (three arcs + a dot, `stroke: currentColor`, `width: 1ch`, `height: 1em`, relative units only). Its id, `title` and `data-state` binding are unchanged.
  - Letter-spacing lives in one custom property: `#topbar { --glyph-ls: 0.04em }`, `.glyph { letter-spacing: var(--glyph-ls) }`.
  - The icon is a `span.glyph` (`#glyph-warnings`) after the sync glyph, with a **fixed** `width: calc(3 * (1ch + var(--glyph-ls)))` and `text-align: start`. Not `min-width: 3ch`: `▲99` is 3 × 16.69 = 50.07 px and 3 ch is only 46.97 px, so a min-width would reflow at two digits.
  - **Width model** (DejaVu Sans Mono 0.60205 em at `--fs-secondary` 26 px; a text character is `1ch + --glyph-ls` = 16.69 px; letter-spacing does not apply to the SVG): BT 33.38 + sync 16.69 + WiFi 15.65 + icon 50.07 = 115.79 px, + 3 × 10 px gaps = **145.8 of 168.6 px. Headroom 22.8 px < 26.69 px**, so no fifth glyph fits. The width test charges every `span.glyph` by its declared width at that rate and fails on any it can't charge. A reader that charged a bare 1 ch would leave 29.0 px of headroom and let a fifth glyph through.
  - ARCH-061's OBD link chain replaces `BT` with the 3-dot SVG at its declared `3ch` (46.97 px; letter-spacing does not apply to an SVG). Cluster: 145.79 − 33.38 (`BT`) + 46.97 = **159.4 of 168.6 px, 9.2 px headroom**: it fits without a re-layout (S110 US-894-a; ceiling 3.5ch). Corrected 2026-10-20 (Atlas PR #115 review F2).

### 4.3 Empty states
**Print only what was assessed** (Atlas 2026-10-14 §5, the ARCH-062 rule applied to the whole page). Superseded: `Engine, system and data all clear.`, which claimed two sources V0.30 doesn't check.
- **Checked, nothing found:** `NO WARNINGS` (26 px, 281.5 px), then `Codes read at h:mm. Engine checks clear.`. The engine clause appears only when `sources.engine.assessed`.
- **Not checked:** `? NOT CHECKED YET`, plus `Trouble codes haven't been read since key-on, so "nothing found" can't be claimed.`
- **Checked, nothing found only**, one line per unassessed source, mono `--fs-meta`, `--text-secondary` (S108 shipped `tone:"secondary"`; Marcus/Iris S109 I1, 2026-10-22). The System line comes first:
  - `sources.system` `{assessed:false, reason:not_read}` ⇒ `System checks not read yet.` (S109 US-877-c: the System checks are built, but not read yet this boot.)
  - `sources.data` `not_built` ⇒ `Data checks are not built yet.`
  - **Not in the NOT CHECKED state** (S109 I2): that state already says "nothing found" can't be claimed, so the line would add nothing.
  - Superseded: `System and data checks are not built yet.` in `--text-tertiary`, shown in both states. After S109 it is false for System.
  - **Deferred, not cancelled:** once System is assessed with no entries, `Engine and system checks clear.` could go on its own line under `Codes read at h:mm.`. It was kept out of S109 (I2). Nothing is lost except saying more of what's true.
- **No data:** while the first read is pending, the US-700 bounded LOADING. After the grace, a missing or unreadable `states/alerts` ⇒ header `--`, body `no warnings data`. The icon shows `--` at the same time (§4.2), so the two never disagree.
- The wording is mine (2026-10-18). The rule (no "clear" for an unassessed source) is Atlas's and not optional.

### 4.4 STOP handling: full-screen takeover (R31, scope ruled 2026-10-14)
**Superseded text:** the first version of this section had no takeover (pulse plus a one-time jump). The CIO kept R31 when asked directly on 2026-10-13. On **2026-10-14 he ruled its scope** (asked directly, via Marcus; this replaces R31's literal "an active red"):
1. **Only a LIVE COOLANT red takes over.** It is the one STOP in Spool's tiers.
2. **RPM red and battery red are WATCH:** the tile goes red from its band, and the icon shows WATCH. **No takeover.**
3. **Stored codes never take over.** A stored code says something happened; a STOP says stop now. No stored class is STOP (Spool 2026-10-14).

**Why the line falls there (Spool's test):** a red is STOP only if (a) the driver's right action is to stop the car **now**, and (b) a takeover cannot arrive after the event is over. Coolant passes both, because it moves slowly and 2.2 s-old data is still the present. RPM fails both: the right action is to lift, and at WOT the pull is over before the frame renders, so a takeover would land mid-shift at full throttle. Battery fails (a): the right action is to get somewhere safe soon, not to stop in the lane.

**Trigger.** The **top active STOP entry** in `states/alerts`. The arbiter decides, and the page never compares a value. Today that can only be live coolant. All of these are **provider rules** (band producer + arbiter, Spool 2026-10-14); the page renders `active` and computes none of them:
- **Fires** at **≥ 110 °C on a sample, or ≥ 104 °C held 120 s** (R26).
- **Plausibility guard:** a single ≥ 110 °C sample counts only if the previous fresh sample was ≥ 100 °C; otherwise two consecutive are needed. Coolant cannot move 10 °C in 2.2 s.
- **Clears** on fresh coolant ≤ 101 °C held 60 s.
- 🔴 **Stale never clears.** If coolant goes stale (> `obdLiveSec`) while the STOP is active, the takeover **stays up** and shows the **last value with its age** (`last reading 12 s ago`, §4.6). An engine that stalled hot is still hot.
- **Key-off** ends the display, not the alarm state. The next key-on re-evaluates from fresh data.

```
┌──────────────────────────────────────────────┐ covers the top bar too; the REPLAY marker stays visible above it
│                                              │
│                PULL OVER                     │ --fs-hero band: takeover.directive (provider)
│              ENGINE OVERHEATING              │ --fs-secondary, own line: takeover.title
│                   234 °F                     │ --fs-primary mono: value + unit (displayUnits)
│             last reading 12 s ago            │ --fs-label mono, own line, ONLY when stale
│  Stop safely, engine off. Do not open the    │ --fs-label mono: takeover.sentence
│  radiator cap hot.                12 s ago   │ --fs-meta: agoText since firstSeenTs
└──────────────────────────────────────────────┘ 8 px --critical-red frame on opaque --bg (stop-alarm-pulse)
```

| Rule | Detail |
|---|---|
| **Words, not colour alone** | Always the directive **plus the value and its unit**. Text survives a single glance; colour alone does not. Words are Spool's (2026-10-14): `PULL OVER` / `ENGINE OVERHEATING` / value / `Stop safely, engine off. Do not open the radiator cap hot.` **The provider supplies all of them:** `takeover.directive` (`PULL OVER`, Atlas G4, 10-18), `title` and `sentence`. The page writes none of them, and the literal `PULL OVER` appears nowhere in `carousel.js` (U11, a file-wide gate once US-899-a2 deletes the old directive strings). The unit is the Driving page's (°F); the thresholds stay in °C in the provider. Never "probably", never a cause on screen. |
| **Stale line** | `last reading n s ago` goes on **its own line at `--fs-label`** (23 characters at most = 276.9 px), never beside the value at `--fs-primary`, where `last reading 999+ s ago` would be 470.8 px against the 464 px inside the frame (S108 review B). Age format per §4.6 |
| **Every page** | It covers **whatever page is showing**. R31 names the Driving page because it is the default, but a red must not hide on another page. That was the reason the old jump existed. |
| **Live red: not dismissable while active** | No control removes it while the provider reports `active` (Spool 06-18). **No button is shown:** `#takeover-detail`, `#takeover-dismiss` and the static `CHECK ENGINE` head are not on this surface (U7), and US-899-a2 deletes them if nothing else uses them. Acknowledge (tap anywhere) stops the **icon** pulse only; the frame keeps pulsing while the takeover is up. |
| **Ends when the cause ends** | When the provider marks the entry inactive (its clear rule above; **never** because the data went stale), the takeover closes and the page underneath returns. The entry stays on Warnings until the arbiter drops it. |
| ~~Stored STOP code~~ | **Removed 2026-10-14:** stored codes never take over. If a code were ever rated STOP, it would show on the icon and the Warnings page only. |
| **Brightness** | **Full brightness while up**, independent of auto-dim. |
| **Motion** | The frame does a slow 2-step pulse. `prefers-reduced-motion`: a steady frame. |
| **Layering** | Above every page, menu and detail overlay. **Below the REPLAY marker only** (Sprint 98 review B-2): a replayed overheat must still say REPLAY. The marker is a direct child of `body` (not of `#topbar`, which is its own stacking context at z 10), with a z-index above the highest declared in `dashboard.css` (US-901-b, as folded by Marcus). `pointer-events` stay on the takeover, never on the marker. |
| **Touch** | Not required at any point (R5). |

Acknowledge is stored by the provider (`POST /alerts-ack {ids: [takeover.id]}`, Atlas 2026-10-14 §3 + Q26), boot-scoped **and keyed to the episode** (Atlas S108 G1: a record counts only when its `bootId` is the current boot AND its `firstSeenTs` equals the entry's), so a kiosk or orchestrator restart does not re-pulse, an acked STOP that cools is removed rather than re-listed unacked (Q15), a new episode under the same id pulses again, and the next key-on re-evaluates. **Honest write**, through the ONE page helper `postWrite(path, body)` that `/dtc-clear` and `/fuel-reset` also use (U12; not `postAction`, which is the `/service-control` helper; each caller keeps its own honest-write rule and the helper never reports success itself): the icon pulse stops only when a re-read shows `acknowledged:true` within `pi.display.stale.alertsAckConfirmSec` (default 6 s, Atlas Q33); otherwise, and on 409/503/504, it keeps pulsing and shows `couldn't acknowledge` (`--fs-meta` mono) for `pi.display.stale.alertsAckNoticeSec` (default 3 s).

**Build: reuse the shipped `#dtc-takeover[data-severity="stop"]` skeleton** (dashboard.css, enforced by `test_dashboard_stop_tier_safety.py`): opaque `--bg`, 8 px `--critical-red` frame on the shipped `stop-alarm-pulse` keyframe (frame → `var(--bg)` at 50 %; **no second alarm red**, Atlas 2026-10-16), `#fff` copy, full brightness (`brightnessAlarmActive` keys on `states/alerts.takeover != null`). The pulse lives inside `@media (prefers-reduced-motion: no-preference)` (U8); the red frame and the words carry STOP without motion. Content from `states/alerts.takeover {id, directive, title, sentence, value, unit, firstSeenTs, dismissable:false}`. The alerts takeover is the ONLY writer of `#dtc-takeover`'s state and copy; z-index 60, below the REPLAY marker's 70.

### 4.4a Live reds that are WATCH (no takeover; Spool 2026-10-14)
The tile on the Driving page is red from its **band**. The Warnings entry is **WATCH** from its **tier**. These are two different facts: band colour says where the value is, and the tier says what the driver should do. The icon follows the tier (amber WATCH), so a red tile with an amber icon is correct, not a contradiction.

| Entry | Words (title / value / sentence) | Clear (provider) |
|---|---|---|
| Battery low (< 12.0 V, running, US-875 gate) | `CHARGING FAULT` / `11.8 V` / `Head somewhere safe. Turn off accessories.` | gate green held 10 s |
| Battery high (> 15.0 V) | `OVERCHARGING` / `15.3 V` / `Head somewhere safe, then engine off.` | gate green held 10 s |
| RPM ≥ red (`params.RPM.scale.redFrom`) | `OVER-REV` / `peak 7,150 rpm (sampled)`; **"(sampled)" is mandatory**, since the true peak can be higher | none during the drive; the drive-end summary carries it |

- **No time-to-stall on screen** for the battery entries: that duration is not sourced (Spool).
- Neither has fired in the corpus: battery 0 of 31,974 gated running samples, all-time max RPM 5,896.

### 4.4b Key-on CODE ALERT (dismissable; CIO 2026-10-14, in S106 2026-10-18)
Stored and pending codes re-alert **once per key-on** and can be hidden. This is a different surface from PULL OVER, with different rules.

```
┌──────────────────────────────────────────────┐ 8 px frame in the TOP tier's chip colour; no pulse
│               TROUBLE CODES                  │ Michroma --fs-secondary (315.5 px)
│ [WATCH] EGR FLOW (P0400)                     │ chip + provider title (mono --fs-label)
│         Drive gently. Get it diagnosed.      │ provider sentence (mono --fs-meta)
│ [MINOR] EVAP PURGE (P0443)                   │
│         Emissions only. Safe to drive.       │
│ +2 more on ALERTS                  [DISMISS] │ real button: bordered, ≥ 40 px (US-758)
└──────────────────────────────────────────────┘
```

| Rule | Detail |
|---|---|
| Source | `states/alerts.codeAlert {ids[], tier, dismissable:true}`. The provider decides when it shows (each key-on, boot-scoped ack) and computes `tier` (Atlas Q32). The page never decides or compares. |
| Container | Its own container, `data-surface="code-alert"`, never `data-severity="watch"` or `"minor"` (U7). Head `TROUBLE CODES`; never the static `CHECK ENGINE` head. |
| Skeleton | The takeover skeleton with **no pulse and no full-brightness override**. Frame colour = `TIER_COLOR_VAR[codeAlert.tier]`, the ONE page map `{stop: --critical-red, watch: --amber-warn, minor: --green-ok, unrated: --neutral-chip-bg}` that PULL OVER also uses (US-899-a1). Never red in practice: no stored code is STOP. UNRATED's `#2a2f37` frame on `#0A0A0A` is low contrast on purpose (an unknown severity doesn't shout); the head and the chips carry it. |
| Rows | Up to 3, each chip + title + sentence looked up by id in `entries[]`; beyond that, `+n more on ALERTS` (mono: `+` and lower case are not in Michroma). |
| DISMISS | Michroma `--fs-label`, bordered, ≥ 40 px hit box. ONE request, `POST /alerts-ack {ids: codeAlert.ids}` (Atlas Q26, all-or-nothing), through `postWrite`. It closes only when a re-read gives `codeAlert == null` within `alertsAckConfirmSec`; otherwise it stays, with `couldn't dismiss` (mono `--fs-meta`) for `alertsAckNoticeSec`. DISMISS is the only control (`DISMISS` 123.0 px at 20 px). |
| 🔴 **Moving** | **Drawn only while `engineParked` is parked** (the US-511 debounce; it starts not-parked, so the alert appears ≥ 8 s after boot — the honest cost of never asserting parked without proof, U6; the page computes no speed rule). It never covers the Driving page at speed (R5). **Hiding it is not a dismiss** and posts nothing: it returns when parked, until dismissed. Key-on is parked, so "re-alert every key-on" holds, 8 s late. |
| Precedence | **PULL OVER > CODE ALERT.** With both up, only PULL OVER is drawn; the code alert returns after the coolant clears. |
| Layering | Above every page, below PULL OVER and below the REPLAY marker (70). |

### 4.5 Code detail + clear
- **Open:** a tap on a CODE row (`source` `code`) opens `#dtc-detail` **only while `engineParked` is parked** (engine off held 8 s, Atlas A7); while not parked (driving, idling stationary, or within the 8 s hold) the row tap does nothing. ENGINE rows are not controls and never open a detail (U10: CODE rows are real controls with a pointer; ENGINE rows and every sentence get no border, fill or pointer).
- **Content (U4):** the directive band shows the entry's **`sentence`** (provider words), never `DTC_TIER`'s tier-table directive. The tier chip comes from the entry; `unrated` renders with the existing `unknown` styling. The code is parsed from the id `code:<code>:<tier>`.
- **The one `states/dtc` read outside the provider path** (a documented G-7 exception, scoped to the detail open and its ticks while open): the full record (long text, freeze-frame/realtime fallback, suggested fix, logged/syncAcked), which also feeds the clear gate. **If that fetch fails**, the detail still renders the entry's own title, tier and sentence plus `details unavailable`, never a cached or tier-table directive.
- **Clear (as shipped, `clearGateReason` unchanged):** offered for MINOR codes only, hard confirm, re-read, refuse a second clear; gate re-checked at the action path (Atlas DTC-A1). Spool: an UNRATED code counts above MINOR (Mode 04 wipes everything, and an unknown can't be judged safe to wipe).
  - WATCH / STOP-tier / UNRATED: **visible, disabled**, with the existing lock label (`🔒 CLEAR CODES — <reason>`, `CLEAR_REASON_LABEL`).
  - **While not parked:** visible, disabled, **`🔒 CLEAR CODES — engine off to clear`** (`CLEAR_REASON_LABEL.moving`; the key name is US-898-c's and is kept, its words are not). Corrected 2026-10-19 (UIDEV-008, the PRD changed the same day):
    - **Why not `car is moving`:** the lock is `engineParked`, which also holds a stationary car with the engine idling and for 8 s after the engine stops. There the old words were false.
    - **Why an instruction:** like the System Settings lock (`🔒 view only — engine off to change`), it says what unlocks the button, which is true in every locked state.
    - No clear-lock text says `moving`.
  - **A permanent reason wins over `moving`** (`severity_present`, `severity_unknown`, `session_locked`, `sync_pending`); `moving` shows only when the gate would otherwise be `ok`. Otherwise a WATCH code seen while driving would say "engine off to clear", implying that turning the engine off unlocks it.

### 4.6 Ages and formats on this page
- **Freshness** (how old the reading I'm showing is): `last reading n s ago`, the S105 M7 rule: `Math.floor`, clamped at 0, `N s` with a space, capped at `999+ s ago`. On stale rows and in the takeover only.
- **Duration** (how long the entry has been wrong): `agoText(now, firstSeenTs)` unchanged, on every row (engine rows too; a battery WATCH active 20 min reads `20 min ago`, not `999+ s ago`) and the takeover's age. Never a short form like `41 d`: `carousel.js` deliberately keeps one age vocabulary.
- Spool's formats (10-19 §5): battery `0.1 V`, one decimal always (`12.0 V`, never `12 V`), **rounded toward the breach** (low alert floors, 11.96 ⇒ `11.9 V`; high alert ceils, 15.04 ⇒ `15.1 V`), so the shown number never sits on the safe side of the threshold that fired. Over-rev: integer rpm, floor, `,` separator, `(sampled)`, composed by the provider into the sentence (Atlas G3).
- **Where the direction lives (Atlas RULED 2026-10-20):** the provider decides and the page applies, as a **direction, never a pre-rounded value**. The entry carries the raw `value` (the current reading, G3) plus `round`: `"floor"` | `"ceil"` | null, set by the arbiter from the band that fired (low ⇒ floor, high ⇒ ceil; null = to-nearest, today's behaviour). `displayUnits` applies it as its **final** step, after unit conversion, at the rule's decimals. Pre-rounding would store a display artefact as a measurement, and would fail for any converted unit (a °C floor, converted and rounded to nearest in °F, can land back on the safe side). No threshold reaches the page. VCs: battery low 11.96 ⇒ `11.9 V`; high 15.04 ⇒ `15.1 V`; `round` null ⇒ byte-identical to today; a stale `last.value` keeps the same direction. A small two-tier story for Marcus to schedule (Spool 10-19 §5 is the source); it does not block S108.

## 5. Data contract
**Authority: Atlas 2026-10-14 WARNINGS ruling** (`states/alerts` shape, boot-scoped ack store, tier mechanism, 4-story split); tokens 2026-10-16. **The page reads `states/alerts` only** for warnings (never `states/dtc`, except in the code-detail view).

| Field | Use | Story |
|---|---|---|
| `icon.{state, count, pulse}` | top-bar icon (§4.2) | US-897-b |
| `sources.code.{assessed, checkedAtTs}` · `sources.engine.assessed` · `sources.system/data.{assessed:false, reason}` | header meta, empty state (§4.3) | US-897-a/b |
| `entries[] {id, source, key, tier, title, sentence, value, unit, firstSeenTs, lastSeenTs, active, stale, acknowledged}`, **already ordered** (tier > live before stored > newest) | the list | US-897-b |
| `takeover` null \| `{id, directive, title, sentence, value, unit, firstSeenTs, dismissable:false}` (`directive`: Atlas G4) | PULL OVER (§4.4) | US-897-b |
| `codeAlert` null \| `{ids[], tier, dismissable:true}` (`tier`: Atlas Q32) | CODE ALERT (§4.4b) | US-897-b |
| `dataSource` | REPLAY/SIM marker above both screens | US-897-b |
| `POST /alerts-ack {ids: [...]}`: token-gated, all-or-nothing (409 `unknown_id` / `not_ackable`, nothing written; Q26), request/outcome channel on the shared helper (US-897-c0), store `/var/lib/eclipse-obd/alerts-ack.json` with records `{id: {bootId, firstSeenTs, ackedAt}}`; an ack counts only for the current boot AND the same episode (`firstSeenTs`, Atlas S108 G1); an acked entry that goes inactive is removed (Q15) | ack + dismiss | US-897-c (S108) |
| Code severities for P0400 (WATCH) and P0443 (MINOR) in the provider table; **no P0430 row** (bank 2, not this car ⇒ UNRATED); the UNRATED sentence | real-codes fixture | **US-754 (S106)** |

- **id = `<source>:<key>:<tier>`**, so an escalation is a new id, and an ack of a lesser state never silences a worse one.
- **Units:** the provider passes the reading's own unit (`C`, `V`, `rpm`). The page converts through the S103 G1 helper by `unit` (coolant shows °F).
- **Words:** every title and sentence is the provider's (Spool 2026-10-14 verbatim). The page composes none. Over-rev: **RULED (Atlas G3, 10-18):** `sentence` = `peak 7,150 rpm (sampled)` with `value` and `unit` null, so "(sampled)" can't be dropped (`value` always means CURRENT, and a drive peak isn't).
- **Not in V0.30:** SYSTEM entries (no `system-status.verdict`, US-877) and DATA entries (US-735 banked). No adapter stubs.

## 6. Acceptance criteria (S108 build, predicates)
From the S106 brief (2026-10-18), U1–U12 and the S108 review (2026-10-19); the S108 PRD carries them per story. Provider-side predicates (B1–B8, c1–c6, Atlas S108 G1/G2) are in the brief and the PRD under US-897-b/c.

**US-898 (icon + page)**
1. For each `icon.state` fixture, the icon DOM matches §4.2. `?` renders only when `icon.state == not_checked`. `icon-missing-payload` ⇒ `--` tertiary, never `△`.
1a. Top-bar width: the reader charges every `span.glyph` by declared width (§4.2) and fails on any it can't charge; the cluster is 145.8 of 168.6 px, and a planted fifth one-character glyph fails. The icon slot does not change width between `▲9` and `▲99`.
2. not-checked: no element's text contains `NONE`, `NO WARNINGS` or `clear`.
3. system-data-not-assessed: no element pairs `system` or `data` with `clear`. The not-built line is present.
4. The DOM row order equals `entries[]`. No `.sort(` in the Warnings render.
5. seven-entries-scroll: all 7 rows in the DOM; at scrollTop 0 `↓ 3 more below` (counted from layout); scrollbar visible; row 1 most severe.
6. UNRATED renders the neutral chip and the provider's sentence (`Severity unknown. Get it diagnosed.`), never a page literal.
7. US-758: no sentence element has a border, fill or `cursor:pointer`. Only real controls look like controls.
8. Battery-red: a red Driving tile beside an amber WATCH icon (band vs tier).
9. Chip inks meet AA per §3.
10. Codes unread + an active WATCH: the icon is watch, not `?`; header meta `codes not read yet`.
10a. Code detail (§4.5): a tap on a code row while not parked (driving, and idling stationary) opens nothing; the band shows the entry's sentence; a failed `states/dtc` fetch ⇒ title, chip, sentence + `details unavailable`; the Clear button is visible and disabled for WATCH/STOP/UNRATED (existing lock label) and while not parked (`🔒 CLEAR CODES — engine off to clear`, tested both driving and idling stationary), with a permanent reason winning over `moving`. No clear-lock text contains `moving`.
10b. Ages: row ages are `agoText` (a `firstSeenTs` 41 days back reads `41 days ago`, no source prefix); a stale row reads `last reading n s ago` and caps at `999+ s ago`.

**US-899 (PULL OVER + CODE ALERT)**
11. stop-live-overheat, on each page in turn: takeover visible; contains the provider's `directive`, the value and its unit; frame animation `stop-alarm-pulse`; applied brightness 1.0.
12. No element inside the takeover is a button. After the ack re-read: `icon.pulse` false, the takeover still up, the entry still listed.
13. `takeover` → null: the takeover hides; the same card index is underneath.
14. stop-live-stale: the takeover stays; `last reading n s ago` on its own `--fs-label` line, and n counts up.
15. Battery-red / RPM-red: no takeover in the DOM; icon watch; the over-rev row contains `(sampled)`.
16. Code-only fixtures never show a STOP takeover.
17. code-alert-keyon (parked): visible, with DISMISS; dismiss → one POST with every id → re-read null → hidden. code-alert-moving: not drawn, no ack posted.
18. ack-prior-boot: the old-boot ack doesn't hold; the pulse and the code alert are back.
18a. Ack an active STOP, then it clears: the entry is removed, never re-listed unacked, and the icon doesn't pulse (Atlas S108 G1, a provider VC the page sees).
19. replay-stop-live: the REPLAY marker's z-index is above the takeover's and above every z-index in dashboard.css (existing marker test).
20. takeover + codeAlert both set: only PULL OVER is drawn.
21. Ack failure (503): the pulse continues; `couldn't acknowledge` shows for `alertsAckNoticeSec`. Never optimistic.
22. **DoD (R15): CIO judgement in the car.** Coolant STOP is desk/replay only; never stage an overheat (Atlas §7).

**Grep gates (carousel.js / dashboard.css / dashboard.html; comments count)**
- G-1. No threshold literals in the warnings/icon/takeover code (110, 104, 101, 7000, 12.0, 15.0).
- G-2. No tier copy literals (`ENGINE OVERHEATING`, `CHARGING FAULT`, `OVERCHARGING`, `OVER-REV`, `GET DIAGNOSED`, `Stop safely`) and **no `PULL OVER` anywhere** (U11; it is `takeover.directive`). Allowed: `TROUBLE CODES`, `DISMISS`, `ALERTS`, the §4.3 lines and the notices.
- G-3. Zero `newSinceTs`, `dtcLastAckedTs`, `takeoverShouldShow`, `dtc-ribbon` (US-899-a2 deletes the dead path and the ribbon, U3).
- G-4. Exactly one `@keyframes stop-alarm-pulse`. No `--critical-red-dim` or `--chip-ink`. `--neutral-chip-bg` only via `var()`.
- G-5. No literal colour or px in new CSS; geometry as scoped custom properties. `#fff` STOP ink is the one exemption.
- G-6. No tier comparison or sort in the render.
- G-7. No `states/dtc` fetch outside the code-detail open.
- G-8. `postAction` is called only from the `/service-control` path; every ack, clear and reset write goes through `postWrite`.

## 7. Fixtures
The S108 build names (`tests/ui/fixtures/states/alerts/`, from the PRD); where the mockup's names differ, these win.
- **Icon:** `icon-none` · `icon-not-checked` · `icon-watch-2` · `icon-stop-pulsing` · `icon-stop-acknowledged` · `icon-count-120` · `icon-missing-payload`.
- **List:** `mixed-live-and-stored` · `two-stored-codes-real` (P0400 WATCH + P0443 MINOR, Spool's titles; needs US-754) · `unrated-code` · `watch-battery-low` · `watch-battery-high` · `watch-over-rev` · `stop-live-overheat` · `stop-live-stale` · `stop-live-cleared`.
- **Empty / scroll:** `checked-clean` · `not-checked` · `system-data-not-assessed` · `codes-unread-with-watch` · `seven-entries-scroll`.
- **PULL OVER:** `stop-acknowledged` · `replay-stop-live` · `ack-fails-503` · `watch-battery-red-no-takeover` (+ `stop-live-overheat`, `stop-live-stale`).
- **CODE ALERT:** `code-alert-keyon` · `code-alert-moving` · `code-alert-and-stop` · `code-alert-five-codes` · `ack-prior-boot`.
- Mockup-only extras: `engine-not-assessed`, `code-alert-dismiss-fails`, stop over Driving. Provider test: `voltage-watch-engine-off-gated`.
- **Retired 2026-10-18:** `mixed-four-sources`, `data-stall-n7` (no SYSTEM/DATA entries in V0.30), `stop-stored-code`.

## 8. Out of scope
Knock alerts (need ECMLink) · AFR/lean numeric (no wideband) · oil pressure (no sensor) · audio alerts (US-538) · SYSTEM and DATA sources (§4.1) · "new ECU, learning" (no swap signal on this car, Spool 10-19).

## 9. Open items
- ~~Atlas G3 / G4 / G6 / G7~~ **RULED 2026-10-18:** value null + `(sampled)` in the sentence; `takeover.directive`; KEEP the dashboard.css:185 mirror; MINOR-/UNRATED-only ⇒ `watch`.
- ~~Spool G1 (UNRATED sentence)~~ **RULED 2026-10-19:** `Severity unknown. Get it diagnosed.` ~~G2 (rows)~~ **RULED 2026-10-18:** P0400 WATCH, P0443 MINOR, no P0430 row.
- **Ruled (Atlas 2026-10-20):** battery toward-the-breach rounding = provider-set `round` direction applied last by `displayUnits` (§4.6). Owed: the two-tier story (Marcus to schedule). Not blocking S108's ACs.
- **Iris:** bring the OEM mockup up to this revision (§10).
- **Top-bar name:** `ALERTS` (86.3 px; `WARNINGS` 125 px doesn't fit the 122 px slot). The page keeps the name Warnings everywhere else.

## 10. Where the v2 OEM mockup is behind this spec (2026-10-19)
The mockup (`specs/v030-warnings-page-oem.html`, v2 of 2026-10-18) predates these folds. **Build from the spec where they differ:**
- the icon's `none` look (`△`), the no-data `--`, the WiFi SVG glyph and the fixed icon slot (§4.2);
- code titles in Spool's `<NAME> (<code>)` form, the UNRATED sentence, no P0430 (§4.1);
- row ages from `agoText`, no source prefix (§3);
- the takeover's directive from the provider and the stale line on its own line (§4.4);
- the clear-button labels (§4.5).

## OEM mockup findings (2026-10-15)
Mockup: `proposals/2026-10-15-v030-warnings-page-oem.html`. Measured: Michroma from the advances table; DejaVu Sans / Sans Mono via PIL.
- **Takeover title** goes on its own line at `--fs-secondary`, with the value in `--font-mono` at `--fs-primary` below it. `ENGINE OVERHEATING` is 544 px in Michroma at 34 px (416 px at 26, which fits 460), and Michroma has no `·` or `°`. §4.4's one-line `ENGINE OVERHEATING · 234 °F` is replaced.
- **"Solid fill"** means an opaque `--bg` with an 8 px `--critical-red` frame, not a red flood.
- **Header fallbacks** (34 px doesn't fit the long pairs):
  - unread with nothing active: `NOT CHECKED` alone, with the reason in the empty state;
  - checked and clean: `NONE` + `codes read h:mm`, and `NO WARNINGS` at 26 px in the empty state;
  - the `?` is `--font-mono` (it isn't in the Michroma subset).
- **Icon precedence:** an active STOP or WATCH outranks `?`. With codes unread, the header meta says `codes not read yet`.
- **Cleared STOP still listed:** outlined chip, dimmed text, `cleared` in the age column. The icon counts active entries only.
- **Over-rev:** title `OVER-REV`, with `peak 7,150 rpm (sampled)` in the sentence slot (mono 15). On one line it is 398 px. ~~Spool to confirm the wording~~ **confirmed (Spool 2026-10-18).**
- **Body height:** 270 px (34 px bar + 16 px dots), not 258 (§3 heading corrected 2026-10-18).
- ~~Open (Atlas token gate)~~ **RULED 2026-10-16: no new tokens.** `--critical-red-dim` rejected (reuse `stop-alarm-pulse`); `--neutral-chip-bg` already exists (#2a2f37, the mockup's #3A3631 was a fork); `--chip-ink` rejected (ink per chip, §3). The v2 mockup follows this.
- ~~UNRATED sentence: Spool's text still owed~~ **RULED 2026-10-19** (§4.1).
