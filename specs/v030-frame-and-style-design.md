# V0.30 page-set frame + visual style — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 · **Status:** CIO-APPROVED (brainstorm 2026-10-12/13), awaiting V0.30 DoD + grooming. Boot/shutdown sequence + Settings mock: **separate spec, still to design.**
**Style mockup:** `proposals/2026-10-13-v030-style-directions.html` → https://claude.ai/artifact/Eeuc311nAqoR5JFa5axvcT (**direction 2, 90s Mitsubishi OEM, is the locked one**)
**DoD lines served:** 7 ("one visual style", R11), 9 (icon on every page)
**Applies to:** every V0.30 page spec (`specs/v030-*-page-design.md`). Where a page spec names a colour token, it now resolves through §4 below.
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Page set (CIO)

| # | Page | Spec |
|---|---|---|
| 1 | **Driving** (default home) | `v030-driving-page-design.md` |
| 2 | Navigation | `v030-navigation-page-design.md` |
| 3 | Engine | `v030-engine-page-design.md` |
| 4 | Fuel | `v030-fuel-page-design.md` |
| 5 | O2 | `v030-o2-page-design.md` |
| 6 | Motion | `v030-motion-page-design.md` |
| 7 | Light | `v030-light-page-design.md` |
| 8 | System (+ details + Settings) | `v030-system-page-design.md` |
| 9 | Warnings | `v030-warnings-page-design.md` |

**R10 amendments recorded by the CIO:** Motion and Light split into two pages; O2 added as its own page; Engine kept as "the ECU's view".

## 2. Navigation (CIO)
- **Unchanged from today: swipe + page dots.** *(Correction: my working note that swipe had been removed by US-746 was stale; the CIO confirms swipe works on the car today.)*
- **No automatic return** to the Driving page. The screen stays where you left it.
- **No timer or event changes the page.** An active STOP does not jump to Warnings: it raises the **R31 full-screen takeover** over whatever page is showing (Warnings spec §4.4). Only a live coolant red is a STOP (CIO 2026-10-14). When the takeover closes, the page underneath is the one the driver left. *(Corrected 2026-10-14: this line said "STOP jump to Warnings, once per new STOP", which R31 superseded on 2026-10-13.)*
- Auto-rotate remains a Settings option (`autoRotateS`, default off).

## 3. Top bar (every page; height `--bar-h` 34)
```
┌──────────────────────────────────────────────┐
│ ●━●━● WIFI SYNC ▲2        7:42           FUEL │
└──────────────────────────────────────────────┘
  left: link chain · WiFi · sync · warning icon   centre: clock   right: PAGE NAME
```
- 3-column grid (US-555 structure kept).
- **Left glyphs:** OBD link chain (System spec §4.2), WiFi (System §4.4), sync, warning icon (Warnings §4.2).
- **Centre:** local 12-hour clock (US-559 helper).
- **Right: the current page name** (CIO). **Pages no longer spend a title row**, returning ~22 px to every page body. **The version string moves to the System → Pi detail.**

### 3.1 Data-source marker (US-901-b; named 2026-10-13 for Marcus's Sprint 98 ask)
When the numbers on the glass are not the car's live data, the clock's slot says so instead. The clock is hidden while the marker is up, because a wall clock is wrong for replayed data.

| Source (`system-status.runMode`, else `obd-live.dataSource`; replay wins) | Marker text |
|---|---|
| `live` and `dataSource` real | *(no marker; clock shows)* |
| `replay` | **`REPLAY`** |
| `simulate` | **`SIM`** |
| any other or unreadable non-live value | **`NOT LIVE`**, at `--fs-meta` so it fits the same box |

- **Why `SIM`, not `SIMULATED`:** the marker sits over the centre slot, and with the left glyph cluster present that slot is only ~100–110 px wide, about what `REPLAY` takes in Michroma at `--fs-label`. `SIMULATED` (~160 px) would paint over the WiFi and sync glyphs. **No marker text may be wider than `REPLAY`**, so one layout check covers all three. `SIM` is the CIO's own word: the flag is `--simulate`, and a simulate run only ever happens at the desk (R37 refuses the production database).
- **Never blank and never hidden:** a non-live value that the page doesn't recognise still raises a marker (`NOT LIVE`). Hiding it would present unknown data as live.
- Look: the same for all three. `--text-primary` on `--bg`, `--font-display` at `--fs-label`, **no state colour and no `--accent`**, because it shows a mode, not a severity. `pointer-events: none`.
- Layering (Marcus's fold): a direct child of `body`, fixed over the centre slot of `--bar-h`, with a z-index above every other declared z-index (so it stays above the R31 takeover).

### 3.2 Page names in the bar (measured 2026-10-14; short names CIO 2026-10-14)
Michroma 400 at `--fs-meta`, letter-spacing 0, inside `.topbar-right` beside the kebab. **Rule: every bar name is ≤ 122 px**, measured from `specs/assets/fonts/michroma/michroma-advances.json`. The budget is 168.6 px of side track, minus an 8 px gap, minus the 34 px kebab, minus a 4 px margin. Never shrink below 15 px: a name that doesn't fit gets a short form.

| Page | Bar name | px |
|---|---|---|
| Driving | `DRIVING` | 88 |
| Navigation | **`NAV`** (CIO) | 48 |
| Engine | `ENGINE` | 80 |
| Fuel | `FUEL` | 53 |
| O2 | `O2` | 30 |
| Motion | `MOTION` | 87 |
| Light | `LIGHT` | 62 |
| System | `SYSTEM` | 95 |
| Warnings | **`ALERTS`** (CIO) | 86 |

The short forms appear **in the bar only**. Each page keeps its full name in specs and stories. Interim V0.29 cards in Sprint 103 use `BATTERY` (104) and `FUEL TRIM` (112), and the Home/IMU card uses `MOTION`.

## 4. Visual style — "90s Mitsubishi OEM" (CIO)

### 4.1 Character
Period-correct for a 1998 Eclipse GST cluster: **matte black, warm-white wide-set lettering, orange-red pointers, soft rounded panels like the gauge bezels.**

### 4.2 Tokens (proposed values; **Atlas gates every addition and change to `tokens.css`**)

| Token | Value | Role |
|---|---|---|
| `--bg` | `#0A0A0A` | matte black field |
| `--surface` | `#141414` | panels, top bar, empty bar segments |
| `--line` *(new)* | `#262626` | rules, panel edges |
| `--text-primary` | `#F5F1E8` | warm white, readings |
| `--text-secondary` | `#A8A296` | labels, units |
| `--text-tertiary` | `#5F5A52` | furniture, inactive dots |
| `--accent` *(new)* | `#FF6A2B` | **pointers + accents only** (§4.4) |
| `--radius` *(new)* | `10px` | panel corners (bezel feel) |
| `--green-ok` / `--amber-warn` / `--critical-red` | **unchanged** | **state only, fixed across styles** |
| `--blue-busy` *(new, UIDEV-018)* | `#4FA8FF` | **activity only:** "in progress". Today its ONE user is the top-bar sync glyph's `busy` state (System §4.3.1, CIO 2026-10-27). Never a severity, never data. Contrast on `--surface` #141414 ≈ 7.4 : 1 |

`--neutral-chip-bg`, `--destructive*`, and the brand reds `--red*` are unchanged (brand reds stay **brand-mark only**).

### 4.3 Type
| Role | Face | Note |
|---|---|---|
| Labels, page names, titles, **the gear glyph** | **Michroma** (OFL) | wide, period look; single weight, so **never synthesise bold** (the Oswald 600-only lesson applies) |
| **Changing readings** (RPM, speed, temps, all values) | **a fixed-width digit face** (current `--font-mono` stack, or an OFL tabular face chosen at build) | digits must not shimmy as they update; wide Michroma digits also overflow the 120 px driving columns |

- **Sizes unchanged:** the F-127 scale (44/34/26/20/15) + `--fs-giant` 120 (driving spec, pending Atlas).
- **Offline embedding:** Michroma must be **embedded as a subset `data:` URI** in `tokens.css`, exactly as Oswald is today (kiosk is offline + CSP-fenced). OFL text ships with the kit. Oswald retires if nothing else binds it.

### 4.4 Colour rules
1. **State colours mean state, only.** Green OK · amber WATCH · red STOP, identical on every page and in every style.
   - **`--blue-busy` means activity, only** (UIDEV-018): something is happening right now. It is not a fourth state tier and is never ranked against them. A new user of blue needs its own spec line.
2. **Green → yellow → red appears ONLY on scales with real bands** from Spool's spec (CIO: "more colour for the graphed data"):
   - RPM bar: green → **yellow from 5,500** (the CIO's display cue, not a shift light; R35) → red from 7,000.
   - History lines (coolant, battery…): coloured **only along the stretches where the provider's band fired** (dwell rules included).
   - Engine numbers on the Driving page: provider band → token.
3. **Unbanded data uses `--accent` orange, never a state colour:** load, throttle, airflow bars, the Navigation hairline, the active page dot, pointers. (Load is never banded on its own, per Spool.)
4. **Readings are warm white**, never orange. The RPM number is white, and turns `--critical-red` only past the redline (CIO).
5. **Night-safe:** dark field; no large bright areas; the accent stays below full intensity on large fills.

## 5. Acceptance criteria (draft, frame-wide)
1. Top bar identical on all nine pages; right slot shows the page name; no page renders its own title row.
2. Swipe and dots both navigate; no timer or event changes the page (auto-rotate off by default). The R31 takeover is an overlay, not a page change.
3. Grep gate: no literal colour/px in any page CSS; every colour resolves to a §4.2 token.
4. No element uses a state colour for unbanded data (fixture review per page).
5. Readings render in the fixed-width face (computed `font-family`) and keep their width across updates.
6. Michroma loads from the embedded payload with the network off (offline kiosk test).
7. **DoD (R15): CIO judgement in the car, day and night.**

## 6. Open items
- ~~Spool: RPM yellow-zone start~~ (5,500, ruled 2026-10-13).
- ~~Atlas: tokens, Michroma, Oswald~~ (ruled 2026-10-13: tokens APPROVED under Rule-10; Michroma as an embedded data: URI subset; Oswald retires if no selector uses it, total embedded-font bytes no larger than today).
- **Iris (next):** boot/shutdown sequence (US-785, US-869, US-870) + the Settings visual mock; re-skin the nine page mockups to §4 once tokens are ratified.
