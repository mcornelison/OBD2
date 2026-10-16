# V0.30 Warnings page + top-bar warning icon — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 (brainstorm 2026-10-12/13; **reworked 2026-10-13 for R31**) · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming. **§4.4 rewritten: the CIO kept the full-screen takeover (R31, Marcus 2026-10-13 14:41). My no-takeover design (WN-3) is superseded. Scope ruled 2026-10-14: only a live coolant red takes over (§4.4, new §4.4a).**
**Mockup:** `proposals/2026-10-12-v030-warnings-page.html` → https://claude.ai/artifact/1hZxFmhcUM8rY5onGu8eXU (**layout A, scrolling, is the locked one**)
**DoD lines served:** 9 (warnings: top-bar icon on every page + own page), 8, 12 (carries US-754, US-758; ARCH-062)
**Builds on:** W-12 unified alert layer (Atlas ruling 2026-06-19: one arbiter-owned `alerts` view-state, an aggregator over providers; tier → live > stored → newest). Spool tiers: `specs/grounded-knowledge.md` DTC severity row + `tuner/dtc-display-clear-safety-advisory.md`.
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose
**Everything that needs attention, ranked, in one place**, with an icon on every page so nothing can hide on a page you aren't looking at.

## 2. Decisions locked (CIO)

| # | Decision | CIO choice |
|---|---|---|
| WN-1 | Sources | **Trouble codes · live engine protection · system issues · data-capture stall** |
| WN-2 | Icon | **4 states + count**: none / not checked / WATCH / STOP |
| WN-3 | Full-screen takeover | ~~None (icon + page only)~~ **SUPERSEDED by R31 (CIO, asked directly 2026-10-13): an active red TAKES OVER the screen. Scope ruled 2026-10-14: LIVE COOLANT red only; RPM/battery red = WATCH; stored codes never** (§4.4). |
| WN-4 | STOP signalling | **Takeover (§4.4) + pulsing red icon.** The one-time jump to Warnings is **dropped**: the takeover already owns the screen, so a jump underneath it does nothing. |
| WN-5 | Live engine protection | **In** (CIO first excluded it, then restored it once shown the gap: an overheat would otherwise show only on the driving page) |
| WN-6 | Clear-code flow | **Keep as shipped** (Mode 04, gated) |
| WN-7 | Order | **One list by severity** |
| WN-8 | Acknowledge | **Stops the pulse + the jump; the entry stays until its cause clears** |
| WN-9 | Layout | **A · Ranked list, showing ALL entries; scrolling allowed** |

## 3. Layout (480 × 320; body 258)

```
┌──────────────────────────────────────────────┐ top bar: … [▲3] (warning icon, every page)
│ 3 ACTIVE                     codes read 6:42 PM│ ~40  --fs-primary
├──────────────────────────────────────────────┤
│ [STOP ] Coolant 232 °F                  ENGINE │ ~50
│         Engine overheating. Pull over…    now │
│ [WATCH] Battery 12.6 V                  ENGINE │
│         Not charging while running.     2 min │
│ [WATCH] P0400                             CODE │
│         EGR flow fault. Get it checked soon.  │
│ [MINOR] P0443                             CODE │ ▓ scrollbar when more
│ ↓ 2 more below                                │
└──────────────────────────────────────────────┘
```

| Element | Tier | Note |
|---|---|---|
| Header | `--fs-primary` | `n ACTIVE` / `NONE` / `NOT CHECKED` (amber) + `codes read h:mm` `--fs-meta` |
| Chip | `--fs-meta` | STOP `--critical-red` · WATCH `--amber-warn` · MINOR `--green-ok` · UNRATED `--neutral-chip-bg` |
| Title | `--fs-label` mono | code or live value |
| Sentence | `--fs-meta` | instruction as **plain text** (US-758) |
| Source / age | `--fs-meta` | ENGINE · CODE · SYSTEM · DATA |

Entries ≥ 48 px tall. **All entries render; the list scrolls** with a visible scrollbar and an `↓ n more below` cue (no silent clip). Ranking means the most severe are always above the fold, so **nothing requires touch while driving** (R5).

## 4. Behaviour

### 4.1 Sources and ranking
| Source | What becomes an entry | Tier |
|---|---|---|
| **CODE** | stored/pending DTCs | Spool's table; **unknown ⇒ UNRATED, never a guessed tier** (US-754). Rated 2026-10-13 (Spool): **P0400 WATCH · P0430 WATCH · P0443 MINOR**. A new UNRATED code on the car is Spool's trigger to rate it; there is no speculative P0 table. |
| **ENGINE** (live) | coolant, battery voltage, RPM over-rev, intake air in a band, **with the dwell rules** | **STOP: live coolant red only.** Battery red and RPM red = **WATCH** (§4.4a). Intake air never above WATCH. |
| **SYSTEM** | whatever the System verdict counts (System spec §4.1) | WATCH |
| **DATA** | capture stalled while the engine runs (US-735), read from `capture-health.feeds` | WATCH. Engine-running predicate ratified (Spool 2026-09-21): accel_z σ > 0.10 for **N = 7** consecutive 10 s buckets (70 s; zero false positives in ~73 h parked). |

Order: **tier (STOP > WATCH > MINOR > UNRATED) → live before stored → newest first** (Atlas 06-19; Spool-confirmed). The **arbiter** orders; the page renders the order it is given.

### 4.2 Top-bar icon (every page)
| State | Condition | Look |
|---|---|---|
| none | checked this session, list empty | grey outline triangle |
| **not checked** | codes **not read this session** (ARCH-062) | amber `?`; **never looks like "all clear"** |
| WATCH | highest active is WATCH/MINOR/UNRATED | amber triangle + count (MINOR-only: grey-text count) |
| STOP | highest active is STOP | red triangle + count; **pulses until acknowledged** |
`prefers-reduced-motion` ⇒ no pulse; a steady red outline instead.

### 4.3 Empty states
- **Checked, nothing found:** `NO WARNINGS`, plus `Codes read at h:mm. Engine, system and data all clear.`
- **Not checked:** `? NOT CHECKED YET`, plus `Trouble codes haven't been read since key-on, so "nothing found" can't be claimed.`

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
- 🔴 **Stale never clears.** If coolant goes stale (> `obdLiveSec`) while the STOP is active, the takeover **stays up** and shows the **last value with its age** (`12 s ago`). An engine that stalled hot is still hot.
- **Key-off** ends the display, not the alarm state. The next key-on re-evaluates from fresh data.

```
┌──────────────────────────────────────────────┐ covers the top bar too; the REPLAY marker stays visible above it
│                                              │
│                PULL OVER                     │ --fs-hero, --critical-red
│                                              │
│        ENGINE OVERHEATING · 234 °F           │ --fs-primary: title + value + unit
│  Stop safely, engine off. Do not open the    │ --fs-label: the provider's sentence
│  radiator cap hot.                12 s ago   │ --fs-meta: since firstSeenTs; when stale, the value's age
└──────────────────────────────────────────────┘ full-bleed --critical-red frame, solid fill
```

| Rule | Detail |
|---|---|
| **Words, not colour alone** | Always the words **`PULL OVER`** plus the **value and its unit**. Text survives a single glance; colour alone does not. Words are Spool's (2026-10-14): `PULL OVER` / `ENGINE OVERHEATING` / value / `Stop safely, engine off. Do not open the radiator cap hot.` The provider supplies the title and sentence; the page never writes them. The unit is the Driving page's (°F); the thresholds stay in °C in the provider. Never "probably", never a cause on screen. |
| **Every page** | It covers **whatever page is showing**. R31 names the Driving page because it is the default, but a red must not hide on another page. That was the reason the old jump existed. |
| **Live red: not dismissable while active** | No control removes it while the provider reports `active` (Spool 06-18). No button is shown. Acknowledge (tap anywhere) stops the **icon** pulse only. |
| **Ends when the cause ends** | When the provider marks the entry inactive (its clear rule above; **never** because the data went stale), the takeover closes and the page underneath returns. The entry stays on Warnings until the arbiter drops it. |
| ~~Stored STOP code~~ | **Removed 2026-10-14:** stored codes never take over. If a code were ever rated STOP, it would show on the icon and the Warnings page only. |
| **Brightness** | **Full brightness while up**, independent of auto-dim. |
| **Motion** | The frame does a slow 2-step pulse. `prefers-reduced-motion`: a steady frame. |
| **Layering** | Above every page, menu and detail overlay. **Below the REPLAY marker only** (Sprint 98 review B-2): a replayed overheat must still say REPLAY. The marker is a direct child of `body` (not of `#topbar`, which is its own stacking context at z 10), with a z-index above the highest declared in `dashboard.css` (US-901-b, as folded by Marcus). `pointer-events` stay on the takeover, never on the marker. |
| **Touch** | Not required at any point (R5). |

Acknowledge is stored by the provider (`POST /alerts-ack`, Atlas §7), so a kiosk restart does not re-pulse.

### 4.4a Live reds that are WATCH (no takeover; Spool 2026-10-14)
The tile on the Driving page is red from its **band**. The Warnings entry is **WATCH** from its **tier**. These are two different facts: band colour says where the value is, and the tier says what the driver should do. The icon follows the tier (amber WATCH), so a red tile with an amber icon is correct, not a contradiction.

| Entry | Words (title / value / sentence) | Clear (provider) |
|---|---|---|
| Battery low (< 12.0 V, running, US-875 gate) | `CHARGING FAULT` / `11.8 V` / `Head somewhere safe. Turn off accessories.` | gate green held 10 s |
| Battery high (> 15.0 V) | `OVERCHARGING` / `15.3 V` / `Head somewhere safe, then engine off.` | gate green held 10 s |
| RPM ≥ red (`params.RPM.scale.redFrom`) | `OVER-REV` / `peak 7,150 rpm (sampled)`; **"(sampled)" is mandatory**, since the true peak can be higher | none during the drive; the drive-end summary carries it |

- **No time-to-stall on screen** for the battery entries: that duration is not sourced (Spool).
- Neither has fired in the corpus: battery 0 of 31,974 gated running samples, all-time max RPM 5,896.

### 4.5 Code detail + clear (as shipped)
Parked-only tap on a CODE entry ⇒ detail (directive-first, carded sections, freeze-frame realtime fallback). **Clear:** MINOR (clearable) codes only, hard confirm, re-read, refuse a second clear; never STOP/WATCH; gate re-checked at the action path (Atlas DTC-A1).

## 5. Data contract

| Need | Status | Owner |
|---|---|---|
| **`states/alerts`**, arbiter emitter in the orchestrator over CODE / ENGINE / SYSTEM / DATA; provider orders the list | **APPROVED to build in V0.30** (Atlas 2026-10-13 §7; provider story 4) | Atlas · Marcus story |
| Per alert `{id, source, tier, title, sentence, firstSeenTs, acknowledged, active}`; `id` = source + key | approved | Atlas |
| `codesCheckedThisSession`, `checkedAtTs` (last good Mode 03 this boot; null ⇒ `?`, ARCH-062) | approved, new | Atlas |
| Ack held by the provider: token-gated `POST /alerts-ack {id}`; clears when the condition ends | approved, new | Atlas |
| Live engine bands with dwell | band producer (R26); Spool's spec sent 2026-10-13 | Spool + Marcus |
| Generic P0 severity | **P0400/P0430 WATCH, P0443 MINOR rated**; others UNRATED | Spool |
| DATA source | `capture-health.feeds.<feed>.{state, firstSampleTs, lastSampleSecondsAgo}` + US-735 N = 7 | Atlas (provider story 2) |
| System issues | `system-status.verdict{issueCount, members[]}` (null is not an issue) | Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. Not-checked fixture: icon `?`, header `NOT CHECKED`, **no** "NONE"/"all clear" text anywhere.
3. Live-coolant-STOP fixture, opened on **each** page in turn: the takeover covers the page and shows the text `PULL OVER`, the value and its unit; the icon is red and pulsing. After acknowledge: no icon pulse, **takeover still up**, entry still listed.
4. Live-coolant-STOP fixture: no control removes the takeover or the entry while the provider reports it `active`. Flip `active` to false: the takeover closes and the page underneath returns unchanged.
4a. ~~Stored-STOP~~ (2026-10-14): a stored-code fixture at any tier **never** raises the takeover.
4d. Stale-STOP fixture (coolant `stale: true`, entry still `active`): the takeover **stays up**, showing `last.value` and its age. Staleness never closes it.
4e. Battery-red and RPM-red fixtures: the tile is red, the icon is WATCH (amber), the Warnings entry carries Spool's words (§4.4a), and **there is no takeover**. The over-rev entry shows `(sampled)`.
4b. Takeover brightness is full regardless of the auto-dim level.
4c. Stylesheet assert (the render harness does no layout): the REPLAY marker's z-index exceeds the takeover's and every other declared z-index in `dashboard.css`, so a future overlay above it fails the suite.
5. Order equals the arbiter's order (fixture with mixed tiers/sources/ages).
6. 7-entry fixture: all 7 reachable by scroll; scrollbar + `n more below` visible; top entries are the most severe.
7. UNRATED code never renders a STOP/WATCH/MINOR chip.
8. No instruction text has button affordance (no border/fill/pointer cursor) (US-758).
9. Clear button absent for STOP/WATCH/UNRATED; absent while moving.
10. No literal colour or px in this page's CSS.
11. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`stop-live-overheat` (takeover) · `stop-live-cleared` · `stop-live-stale` (takeover stays) · `watch-battery-low` · `watch-battery-high` · `watch-over-rev` · ~~`stop-stored-code`~~ · `two-stored-codes-real` (P0400 WATCH, P0443 MINOR) · `unrated-code` · `mixed-four-sources` · `checked-clean` · `not-checked` · `seven-entries-scroll` · `stop-acknowledged` · `voltage-watch-engine-off-gated` · `data-stall-n7` · `replay-stop-live`.

## 8. Out of scope
Knock alerts (need ECMLink) · AFR/lean numeric (no wideband) · oil pressure (no sensor) · audio alerts (US-538).

## 9. Open items
- ~~Spool: ratify §4.4~~ (moot under R31) · ~~US-754 for the car's codes~~ (rated) · ~~US-735 predicate~~ (N = 7). **Still Spool:** rate any new UNRATED code; the band story.
- **Atlas:** arbiter story 4 (approved). Fold the 2026-10-14 scope into it: STOP = live coolant only, RPM/battery red = WATCH entries with Spool's words, the plausibility guard, the clear rules, and stale-never-clears. ~~Confirm a stored STOP drives the takeover~~ (moot: stored codes never take over).
- ~~**Marcus:** R31 scope~~ **(CIO ruled 2026-10-14, via Marcus):** live coolant red only takes over; RPM + battery red = WATCH; stored codes never take over (§4.4).
- **Top-bar name:** this page shows **`ALERTS`** in the bar (CIO 2026-10-14; `WARNINGS` at 125 px doesn't fit the 122 px slot). The page keeps the name Warnings everywhere else (frame spec §3.2).
- **Mockup:** the published Warnings mockup still shows the no-takeover version; a takeover frame is owed in the next mockup pass.

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
- **Over-rev:** title `OVER-REV`, with `peak 7,150 rpm (sampled)` in the sentence slot (mono 15). On one line it is 398 px. **Spool to confirm the wording.**
- **Body height:** 270 px (34 px bar + 16 px dots), not 258.
- ⚠️ **Open (Atlas token gate):** the mockup uses three tokens not in `tokens.css`: `--critical-red-dim` (the pulse's second step), `--neutral-chip-bg` (named by this spec, undefined) and `--chip-ink`.
- ⚠️ **Open (Spool/Atlas):** an UNRATED code needs a provider sentence. The mockup's `Not rated for this car yet.` is a placeholder.
