# V0.30 Warnings page + top-bar warning icon — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 (brainstorm 2026-10-12/13; **reworked 2026-10-13 for R31**) · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming. **§4.4 rewritten: the CIO kept the full-screen takeover (R31, Marcus 2026-10-13 14:41). My no-takeover design (WN-3) is superseded. Scope ruled 2026-10-14: only a live coolant red takes over (§4.4, new §4.4a).** **S106 brief folded 2026-10-18 (UIDEV-005):** the key-on CODE ALERT (§4.4b, CIO put it in S106), SYSTEM/DATA not in V0.30 (Atlas §5), the empty state prints only what was assessed (§4.3), tokens ruled, and §5–§7 rewritten as the build contract. Brief: `pm/inbox/2026-10-18-from-iris-S106-brief-Warnings-US-897-898-899-specs-fields-ACs-gates-gaps.md`.
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
| Header | `--fs-primary` | `n ACTIVE` / `NONE` (142.4 px) / `NOT CHECKED` (amber, 352.7 px) + `codes read h:mm` `--fs-meta` (12-hour, no AM/PM: the one clock rule) |
| Chip | `--fs-meta` | STOP `--critical-red`, ink `#fff` (the existing STOP copy colour, 4.98) · WATCH `--amber-warn`, ink `var(--bg)` (12.4) · MINOR `--green-ok`, ink `var(--bg)` (8.73) · UNRATED `--neutral-chip-bg` (#2a2f37, tokens.css SSOT), ink `--text-primary` (11.94). **No new tokens** (Atlas 2026-10-16, contrast MEASURED). |
| Title | `--fs-label` mono | code or live value |
| Sentence | `--fs-meta` | instruction as **plain text** (US-758) |
| Source / age | `--fs-meta` | ENGINE · CODE · SYSTEM · DATA |

Entries ≥ 48 px tall. **All entries render; the list scrolls** with a visible scrollbar and an `↓ n more below` cue (no silent clip). Ranking means the most severe are always above the fold, so **nothing requires touch while driving** (R5).

## 4. Behaviour

### 4.1 Sources and ranking
| Source | What becomes an entry | Tier |
|---|---|---|
| **CODE** | stored/pending DTCs | Spool's table; **unknown ⇒ UNRATED, never a guessed tier** (US-754). Rated 2026-10-13 (Spool): **P0400 WATCH · P0430 WATCH · P0443 MINOR**. ⚠️ **Not yet in any provider table** (Atlas MEASURED 2026-10-16: the live car publishes both as `unknown`); **US-754 carries the rows, in S106.** A new UNRATED code on the car is Spool's trigger to rate it; there is no speculative P0 table. |
| **ENGINE** (live) | coolant, battery voltage, RPM over-rev, intake air in a band, **with the dwell rules** | **STOP: live coolant red only.** Battery red and RPM red = **WATCH** (§4.4a). Intake air never above WATCH. |
| **SYSTEM** | ⏸ **not in V0.30.** `system-status` has no `verdict` yet (US-877 not built), so the provider publishes `sources.system.assessed:false`. When built: whatever the System verdict counts (System spec §4.1) | WATCH |
| **DATA** | ⏸ **not in V0.30.** The engine-running stall predicate (US-735) is banked (CIO R33), so a stall can't be told from engine-off; `sources.data.assessed:false`. When built: capture stalled while the engine runs, from `capture-health.feeds` | WATCH. Predicate ratified (Spool 2026-09-21): accel_z σ > 0.10 for **N = 7** consecutive 10 s buckets. |

Order: **tier (STOP > WATCH > MINOR > UNRATED) → live before stored → newest first** (Atlas 06-19; Spool-confirmed). The **arbiter** orders; the page renders the order it is given.

### 4.2 Top-bar icon (every page)
| State | Condition | Look |
|---|---|---|
| none | checked this session, list empty | grey outline triangle |
| **not checked** | codes **not read this session** (ARCH-062) | amber `?`; **never looks like "all clear"** |
| WATCH | highest active is WATCH/MINOR/UNRATED | amber triangle + count. ~~MINOR-only: grey-text count~~: **proposed (Atlas G7)** the provider maps MINOR-/UNRATED-only to `watch`, since they are counted and counted means amber (CIO 2026-10-16) |
| STOP | highest active is STOP | red triangle + count; **pulses until acknowledged** |
`prefers-reduced-motion` ⇒ no pulse; a steady red outline instead.
**The provider computes the state** (`states/alerts.icon {state: none|not_checked|watch|stop, count, pulse}`); the page renders it and compares nothing. An active STOP or WATCH outranks `?`. Tapping the icon opens Warnings (a control: 40 px hit box).

### 4.3 Empty states
**Print only what was assessed** (Atlas 2026-10-14 §5, the ARCH-062 rule applied to the whole page). Superseded: `Engine, system and data all clear.`, which claimed two sources V0.30 doesn't check.
- **Checked, nothing found:** `NO WARNINGS` (26 px, 281.5 px), then `Codes read at h:mm. Engine checks clear.`. The engine clause appears only when `sources.engine.assessed`.
- **Not checked:** `? NOT CHECKED YET`, plus `Trouble codes haven't been read since key-on, so "nothing found" can't be claimed.`
- **Both states**, while `sources.system` or `sources.data` is `assessed:false`, add one line in `--text-tertiary`: `System and data checks are not built yet.`
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

Acknowledge is stored by the provider (`POST /alerts-ack {id}`, Atlas 2026-10-14 §3), boot-scoped, so a kiosk or orchestrator restart does not re-pulse and the next key-on re-evaluates. **Honest write:** the icon pulse stops only when the re-read says `acknowledged:true`; on failure (503 in fixture mode) it keeps pulsing and shows `couldn't acknowledge` (`--fs-meta`, 3 s).

**Build: reuse the shipped `#dtc-takeover[data-severity="stop"]` skeleton** (dashboard.css, enforced by `test_dashboard_stop_tier_safety.py`): opaque `--bg`, 8 px `--critical-red` frame on the shipped `stop-alarm-pulse` keyframe (frame → `var(--bg)` at 50 %; **no second alarm red**, Atlas 2026-10-16), `#fff` copy, full brightness. Content from `states/alerts.takeover {id, title, sentence, value, unit, firstSeenTs}`; while the entry is `stale` the age reads `last reading n s ago`.

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
│ [WATCH] P0400                                │ chip + code (mono --fs-label)
│         EGR flow fault. Get it checked soon. │ provider sentence --fs-meta
│ [MINOR] P0443                                │
│         Evap purge valve circuit.            │
│ +2 more on ALERTS                  [DISMISS] │ real button: bordered, ≥ 40 px (US-758)
└──────────────────────────────────────────────┘
```

| Rule | Detail |
|---|---|
| Source | `states/alerts.codeAlert {ids[], dismissable:true}`. The provider decides when it shows (each key-on, boot-scoped ack). The page never decides. |
| Skeleton | Same as PULL OVER, with **no pulse and no full-brightness override**. Frame = the chip colour of the highest tier among `ids` (amber WATCH / green MINOR / neutral UNRATED). Never red: no stored code is STOP. |
| Rows | Up to 3 (chip + code + the provider's sentence); beyond that, `+n more on ALERTS`. |
| DISMISS | `POST /alerts-ack` for each id. It closes only when the re-read gives `codeAlert == null`; on failure it stays, with `couldn't dismiss`. DISMISS is the only control (`DISMISS` 123.0 px at 20 px). |
| 🔴 **Moving** | **Not drawn while moving** (the W-13 `parked` predicate + `drive.state`; the page computes no speed rule). It never covers the Driving page at speed (R5). **Hiding it is not a dismiss:** it returns when parked, until dismissed. Key-on is normally parked, so "re-alert every key-on" holds. |
| Precedence | **PULL OVER > CODE ALERT.** With both up, only PULL OVER is drawn; the code alert returns after the coolant clears. |
| Layering | Above every page, below PULL OVER and below the REPLAY marker. |

### 4.5 Code detail + clear (as shipped)
Parked-only tap on a CODE entry ⇒ detail (directive-first, carded sections, freeze-frame realtime fallback). **Clear:** MINOR (clearable) codes only, hard confirm, re-read, refuse a second clear; never STOP/WATCH; gate re-checked at the action path (Atlas DTC-A1).

## 5. Data contract
**Authority: Atlas 2026-10-14 WARNINGS ruling** (`states/alerts` shape, boot-scoped ack store, tier mechanism, 4-story split); tokens 2026-10-16. **The page reads `states/alerts` only** for warnings (never `states/dtc`, except in the code-detail view).

| Field | Use | Story |
|---|---|---|
| `icon.{state, count, pulse}` | top-bar icon (§4.2) | US-897-b |
| `sources.code.{assessed, checkedAtTs}` · `sources.engine.assessed` · `sources.system/data.{assessed:false, reason}` | header meta, empty state (§4.3) | US-897-a/b |
| `entries[] {id, source, key, tier, title, sentence, value, unit, firstSeenTs, lastSeenTs, active, stale, acknowledged}`, **already ordered** (tier > live before stored > newest) | the list | US-897-b |
| `takeover` null \| `{id, title, sentence, value, unit, firstSeenTs, dismissable:false}` | PULL OVER (§4.4) | US-897-b |
| `codeAlert` null \| `{ids[], dismissable:true}` | CODE ALERT (§4.4b) | US-897-b |
| `dataSource` | REPLAY/SIM marker above both screens | US-897-b |
| `POST /alerts-ack {id}`: token-gated, request/outcome channel, `/var/lib/eclipse-obd/alerts-ack.json`, counts only for the current `bootId` | ack + dismiss | US-897-c |
| Code severities for P0400/P0430/P0443 in the provider table | real-codes fixture | **US-754 (S106)** |

- **id = `<source>:<key>:<tier>`**, so an escalation is a new id, and an ack of a lesser state never silences a worse one.
- **Units:** the provider passes the reading's own unit (`C`, `V`, `rpm`). The page converts through the S103 G1 helper by `unit` (coolant shows °F).
- **Words:** every title and sentence is the provider's (Spool 2026-10-14 verbatim). The page composes none. Over-rev: proposed `sentence` = `peak 7,150 rpm (sampled)` with `value` null, so "(sampled)" can't be dropped (Atlas G3).
- **Not in V0.30:** SYSTEM entries (no `system-status.verdict`, US-877) and DATA entries (US-735 banked). No adapter stubs.

## 6. Acceptance criteria (S106 build, predicates)
From the S106 brief (2026-10-18). Provider-side predicates (B1–B8, c1–c6) are in the brief under US-897-b/c.

**US-898 (icon + page)**
1. For each `icon.state` fixture, the icon DOM matches §4.2. `?` renders only when `icon.state == not_checked`.
2. not-checked: no element's text contains `NONE`, `NO WARNINGS` or `clear`.
3. system-data-not-assessed: no element pairs `system` or `data` with `clear`. The not-built line is present.
4. The DOM row order equals `entries[]`. No `.sort(` in the Warnings render.
5. seven-entries: all 7 rows in the DOM; `↓ n more below` visible at scrollTop 0; scrollbar visible; row 1 most severe.
6. UNRATED renders the neutral chip and the provider's sentence (null ⇒ no sentence, never a page literal).
7. US-758: no sentence element has a border, fill or `cursor:pointer`. Only real controls look like controls.
8. Battery-red: a red Driving tile beside an amber WATCH icon (band vs tier).
9. Chip inks meet AA per §3.
10. Codes unread + an active WATCH: the icon is watch, not `?`; header meta `codes not read yet`.
10a. Code detail (§4.5, kept): the Clear button is absent for STOP/WATCH/UNRATED codes and absent while moving.

**US-899 (PULL OVER + CODE ALERT)**
11. stop-live-overheat, on each page in turn: takeover visible; contains `PULL OVER`, the value and its unit; frame animation `stop-alarm-pulse`; applied brightness 1.0.
12. No element inside the takeover is a button. After the ack re-read: `icon.pulse` false, the takeover still up, the entry still listed.
13. `takeover` → null: the takeover hides; the same card index is underneath.
14. stale-coolant-stop: the takeover stays; age `last reading n s ago`, and n counts up.
15. Battery-red / RPM-red: no takeover in the DOM; icon watch; the over-rev row contains `(sampled)`.
16. Code-only fixtures never show a STOP takeover.
17. code-alert-keyon (parked): visible, with DISMISS; dismiss → re-read null → hidden. code-alert-moving: not drawn, no ack posted.
18. ack-prior-boot: the old-boot ack doesn't hold; the pulse and the code alert are back.
19. replay-stop-live: the REPLAY marker's z-index is above the takeover's and above every z-index in dashboard.css (existing marker test).
20. takeover + codeAlert both set: only PULL OVER is drawn.
21. Ack failure (503): the pulse continues; `couldn't acknowledge` shows. Never optimistic.
22. **DoD (R15): CIO judgement in the car.** Coolant STOP is desk/replay only; never stage an overheat (Atlas §7).

**Grep gates (carousel.js / dashboard.css)**
- G-1. No threshold literals in the warnings/icon/takeover code (110, 104, 101, 7000, 12.0, 15.0).
- G-2. No tier copy literals (`ENGINE OVERHEATING`, `CHARGING FAULT`, `OVERCHARGING`, `OVER-REV`, `GET DIAGNOSED`, `Stop safely`). Allowed: `PULL OVER` (pending Atlas G4), `TROUBLE CODES`, `DISMISS`, `ALERTS`, the §4.3 lines.
- G-3. Zero `newSinceTs`, `dtcLastAckedTs`, `takeoverShouldShow` (US-899 deletes the dead path).
- G-4. Exactly one `@keyframes stop-alarm-pulse`. No `--critical-red-dim` or `--chip-ink`. `--neutral-chip-bg` only via `var()`.
- G-5. No literal colour or px in new CSS; geometry as scoped custom properties. `#fff` STOP ink is the one exemption.
- G-6. No tier comparison or sort in the render.
- G-7. No `states/dtc` fetch outside the code-detail view.

## 7. Fixtures
All drawn in the OEM mockup (`specs/v030-warnings-page-oem.html`).
- **PULL OVER:** `stop-live-overheat` · `stop-live-stale` · `stop-acknowledged` · `ack-fails-503` · `stop-live-cleared` · `replay-stop-live` · stop over Driving.
- **CODE ALERT:** `code-alert-keyon` · `code-alert-moving` · `code-alert-and-stop` · `code-alert-dismiss-fails` · `ack-prior-boot`.
- **List:** `watch-battery-low` · `watch-battery-high` · `watch-over-rev` · `two-stored-codes-real` (needs US-754) · `unrated-code` · `mixed-live-and-stored` · `seven-entries-scroll`.
- **Empty / icon:** `checked-clean` · `engine-not-assessed` · `not-checked` · `codes-unread-with-watch`. Plus `system-data-not-assessed` (= checked-clean in V0.30) and `voltage-watch-engine-off-gated` (a provider test).
- **Retired 2026-10-18:** `mixed-four-sources`, `data-stall-n7` (no SYSTEM/DATA entries in V0.30), `stop-stored-code`.

## 8. Out of scope
Knock alerts (need ECMLink) · AFR/lean numeric (no wideband) · oil pressure (no sensor) · audio alerts (US-538).

## 9. Open items
- **Atlas (S106 brief gaps):**
  - G3: the over-rev shape (sentence carries `(sampled)`, value null).
  - G4: `PULL OVER` as a page literal or `takeover.directive`. I lean to the provider field.
  - G6: dashboard.css:185 re-declares `--neutral-chip-bg`; drop it in US-898, or rule it fine.
  - G7: MINOR-/UNRATED-only maps to icon `watch`.
- **Spool:**
  - G1: the UNRATED provider sentence. Until it exists, null and no placeholder. Confirm "not rated" is never phrased as safe.
  - G2: the P0400/P0430/P0443 rows via US-754 (S106).
- **Marcus** grooms S106 once this fold, G3/G4/G6/G7 and G1/G2 land.
- ~~Mockup owes a takeover frame~~ **done** (OEM v2, 2026-10-18, PULL OVER + CODE ALERT).
- **Top-bar name:** `ALERTS` (86.3 px; `WARNINGS` 125 px doesn't fit the 122 px slot). The page keeps the name Warnings everywhere else.

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
- **Body height:** 270 px (34 px bar + 16 px dots), not 258 (§3 heading corrected 2026-10-18).
- ~~Open (Atlas token gate)~~ **RULED 2026-10-16: no new tokens.** `--critical-red-dim` rejected (reuse `stop-alarm-pulse`); `--neutral-chip-bg` already exists (#2a2f37, the mockup's #3A3631 was a fork); `--chip-ink` rejected (ink per chip, §3). The v2 mockup follows this.
- **UNRATED sentence: RULED provider-owned (Atlas 2026-10-16); Spool's text still owed (§9 G1).** The v2 mockup draws no sentence (null), not the old placeholder.
