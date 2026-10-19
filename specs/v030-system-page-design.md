# V0.30 System page (+ detail screens + Settings) — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12). **S110 fold 2026-10-19 (UIDEV-007):**
- the CIO's rulings of 2026-10-19 (UPS row, power mode, ⋮ while not parked, brightness, and auto-dim ends settable; Marcus C1–C4 corrections folded the same day);
- the S109 providers as groomed (verdict members, per-layer link, WiFi, sync, Pi health);
- my S109 words;
- the shipped Settings band, whose words win.

Per-id answers to Marcus: S1–S10. Where this spec and an older note disagree, this spec wins.

**Mockup:** `proposals/2026-10-12-v030-system-page.html` → https://claude.ai/artifact/47FkWPp39fVQL3ciKph8ra (**layout A is the locked one**). OEM skin: https://claude.ai/artifact/XXpv3Qn3vUzJj7j4TJfF74.
- ⚠️ Both mockups predate this fold. They still show `≈ 92 %` and `on car power` on the UPS row, a power-mode row and an amber weak-WiFi glyph.
- §4 and §4.7 win over both mockups (§10 lists the gaps).

**DoD lines served:** 7 (themed pages: System + power), 8, 12 (closes ARCH-061 and US-713; carries US-729, US-732, US-742, US-759 as rules)
**Also:** F-126 Settings, **brought INTO V0.30 by the CIO 2026-10-12** (reverses R16 for F-126). **S110 stories:** US-894 System page · US-895 Settings · US-878-c brightness override.
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose (CIO)
**"Is everything OK?"** A verdict first, then one row per subsystem with a state and a plain sentence. Diagnostics live one tap away (parked).

## 2. Decisions locked (CIO, 2026-10-12; amended 2026-10-19)

| # | Decision | CIO choice |
|---|---|---|
| S-1 | Structure | **One summary page + detail screens** |
| S-2 | Purpose | "Is everything OK?" |
| S-3 | UPS level | **Voltage first.** Never a runtime. **SOC only in the UPS detail, marked modelled** (Spool 2026-10-19: SOC must not read as a readiness signal) |
| S-4 | OBD link | **3-step chain** BT → ADAPTER → ECU; compact 3-dot version in the top bar |
| S-5 | Rows | **OBD link · capture + sync · WiFi · UPS** |
| S-6 | Pi health | **Detail only**, opened from the verdict line |
| S-7 | Settings access | **Both**: SETTINGS button on System **and** the ⋮ overlay |
| S-8 | WiFi | **Green home · neutral other network (CIO 2026-10-16) · grey down · `--` not read · amber `? not read` only when the read failed** |
| S-9 | Layout | **A · Verdict and rows** |
| S-10 | ECU silent with BT + adapter up | **Not an issue**: grey step + `ECU not answering (key off?)` |
| S-11 | Settings contents | **Brightness override (US-878-c, CIO 2026-10-19 IN)** · **auto-dim ends (`luxMin` / `luxFull`; CIO 2026-10-19 reversed Atlas ruling B, Atlas acked)** · auto-rotate · calibration · auto-analyze. ~~Power mode~~ **DROPPED** (CIO 2026-10-19; already deleted from the code by US-668) |
| S-12 | UPS power source (CIO 2026-10-19) | **External or battery only, never wall / car.** The Pi can't tell those two apart, and the US-668 ruling stands: if the screen is lit, the power is on |
| S-13 | ⋮ while not parked (CIO 2026-10-19, US-659) | **The ⋮ stays visible and openable while driving.** Its Settings band stays, and **every control is locked read-only until parked**: engine off, held 8 s (Atlas A7, CIO accepted; §4.7.2) |

**Why three layers and not "powered / BT / ECU" (ARCH-061's wording):** the Pi cannot measure "dongle powered"; an unpowered dongle and an out-of-range one look identical. It **can** measure Bluetooth `Connected`, the ELM adapter answering AT commands (works key-off), and the ECU answering. Those three are the honest layers.

## 3. Layout (480 × 320; body 270 = 320 − 34 bar − 16 dots)

```
┌──────────────────────────────────────────────┐ top bar: ●━●━○ ⇅ ((•)) ▲ (chain as 3 dots, §4.2.1)
│ ALL OK                           SETTINGS ›  │ ~40  verdict --fs-primary
├──────────────────────────────────────────────┤
│ OBD    [BT]━[ADAPTER]━[ECU]                   │ ~48
│        ECU not answering (key off?)          │
├──────────────────────────────────────────────┤
│ DATA   idle · synced 6:42 PM                 │ ~48
│        not driving · 0 rows waiting          │
├──────────────────────────────────────────────┤
│ WIFI   home                                  │ ~48
│        DeathstarWifi · good signal           │
├──────────────────────────────────────────────┤
│ UPS    4.12 V                                │ ~48
│        on external power · 12 s ago          │
└──────────────────────────────────────────────┘
```

- **Type:**
  - row label `--fs-label` `--font-display`;
  - value `--fs-label` mono, in its state colour;
  - sentence `--fs-meta` mono, 9.03 px per character on the Pi's DejaVu Sans Mono, ≈ 40 characters in the ≈ 368 px sentence column.
- These rows are **read parked or glanced for colour**. The verdict is the driver-glance element (`--fs-primary`).
- **Every row is ≥ 44 px tall** (a touch target when parked).
- **Long text ellipsizes on one line**, and the full text is in the row's detail. That's no silent clip: the ellipsis is the visible sign.

## 4. Behaviour

### 4.0 The colour rule (🔴 load-bearing)
**Amber means counted, and counted means amber.** Every amber element is a member of the verdict count, and every counted member shows amber somewhere on the page (AC 7). An amber row under `ALL OK` is a false instrument.
- **Expected states are neutral and uncounted:**
  - Bluetooth `connecting…` at key-on;
  - WiFi on another network, `weak` WiFi, or WiFi `down`;
  - the UPS on battery;
  - a DEGRADED / REPLACE battery verdict.
- Each renders in `--text-secondary` or `--text-tertiary` with its sentence.
- **Counting expected states would put `1 ISSUE` on the glass at every key-on** and train the driver to ignore the verdict, the same failure as the coolant 100 °C band. CIO RULED 2026-10-16.
- The page compares nothing. Which states count is the provider's `verdict` (Atlas 08-20). The page paints amber exactly on the members it is given.

### 4.1 Verdict (S1)
- **Value:** `ALL OK` (`--green-ok`) when `verdict.issueCount == 0`, else `n ISSUE` / `n ISSUES` (`--amber-warn`), from `system-status.verdict {issueCount, members[{key, reason}]}`.
- **The count names its members** (carries US-759): each member's row or line shows amber, and nothing else does.
- **S109 members, in this fixed order:**

| key | Counted when (provider) | Where the amber shows |
|---|---|---|
| `bt` | `link.bt` down or retrying (not `connecting`) | OBD row: BT step + sentence |
| `adapter` | adapter not answering while `link.bt` up | OBD row: ADAPTER step + sentence |
| `capture` | a feed stalled while `link.ecu` up | DATA row: value `stalled` + sentence |
| `wifi` | the WiFi read **failed** (`reason: read_failed`) | WIFI row: `? not read` |
| `pi` | `pi.overLimit` non-empty | the Pi line under the verdict |

- **Not members (S109):**
  - **`sync`:** banked as US-917, with my sync words in its goal. Until it lands, a sync failing at home is **shown, never counted**. The DATA sentence says it, neutral.
  - **UPS:** no grounded band (Spool + Atlas P5).
  - ECU silent (S-10), away from home, WiFi down, WiFi weak, WiFi not read for want of a tool (`nmcli_absent`), and any null.
- **The Pi line** shows only when `pi` is a member. It's one mono `--fs-meta` line in amber under the verdict, carrying the member's `reason` verbatim plus ` ›`, e.g. `CPU 80.2 °C, limit 80 °C. ›`. Tap it (parked) ⇒ **Pi health** detail.
- **No verdict** (`verdict` absent or the file unreadable): the value is `--` in `--text-tertiary`, never `ALL OK`. `ALL OK` is the provider's claim that it looked.

### 4.2 OBD chain (S2)
The provider publishes a state per layer (`link.bt`, `link.adapter`, `link.ecu`): `up` / `connecting` / `retrying` / `down` / `null`, each with `available` + `ts` for **this session** (ARCH-062).

| Layer state | Step look | Counted |
|---|---|---|
| `up` | `--green-ok` outlined step | no |
| `connecting` (first link since key-on) | `--text-secondary`, neutral | no (CIO 2026-10-16; still closes US-713, because the step and sentence say `connecting…`) |
| `retrying` (was up this session, dropped) | `--amber-warn` | yes, if it's a member |
| `down` | `--text-tertiary`, solid outline | only if it's a member (`bt`, or `adapter` while BT is up) |
| `null` (not read this session) | `--text-tertiary`, **dashed** outline, label kept | never |

- `null` is new in this fold. It's the ARCH-062 rule as a look: a step we didn't read must not look like a step we read as down. **Dashed = no reading; solid = a reading.**
- **Sentence, one rule:**
  1. **If the row has a verdict member (`bt` or `adapter`), print that member's `reason` verbatim.** Those are the S109 words, e.g. `Link dropped. Retrying.` / `Not linked. Check the OBD dongle.` / `Bluetooth up; adapter not answering.` Then the Warnings entry and this row can never disagree, because they're one string.
  2. **Otherwise**, the page looks up the first non-`up` layer's state in a fixed table. That's a lookup on a provider enum, not a comparison, the same pattern as `LIGHT_REASON_TEXT`:

| First non-up layer → state | Sentence |
|---|---|
| bt `connecting` | `Bluetooth connecting… (takes ~1 min)` |
| adapter `connecting` | `adapter connecting…` |
| ecu `down` or `connecting` (BT + adapter up) | `ECU not answering (key off?)` |
| any layer `null` | `not read yet` |
| all `up` | `ECU answering` |

- **Retired:** the old `Bluetooth not linked` and `adapter not answering` sentences. The member reasons replace them.
- **ARCH-061:** no element reads "Bluetooth down".

#### 4.2.1 Top-bar chain (every page; S8)
- **Look:** three dots joined by short lines, **replacing the single `BT` glyph**. That closes ARCH-061: one icon covering three facts never returns.
- **Build:** one inline SVG (`stroke`/`fill: currentColor` per dot, relative units only), `width: 3ch; height: 1em`. Each dot takes its layer's state colour from the table above, and a `null` layer is a hollow ring.
- **Width budget (MEASURED model, S108 four-item cluster at the 26 px bar face, 0.60205 em advance):**
  - **Today:** `BT` 33.38 + sync 16.69 + WiFi SVG 15.65 + warnings icon 50.07 + 3 × 10 px gaps = 145.8 of the 168.6 px side track.
  - **With the chain:** it replaces `BT` at 3ch = **46.96 px**, so the cluster is **159.4 of 168.6, headroom 9.2 px**. Letter-spacing doesn't apply to an SVG, so 3ch is exact.
  - **Limit:** the chain may not exceed **3.5ch** (54.8 px, headroom 1.4). `test_topbar_three_column_grid` re-measures the cluster against the track, and that test is the gate, not this arithmetic.
- **Ids:** the `#glyph-bt` id, its `title` and the click target are kept, so existing tests find it.

### 4.3 DATA (capture + sync; S4)
- **Value:**
  - the capture state from `capture-health`: `recording` / `idle` (not driving) / `stalled` (amber, the `capture` member);
  - then ` · synced h:mm AM` from `sync.lastOkTs` ("last data stored", S109 Rule 10), through `fmtTimeOfDay`, the US-559 local-time helper;
  - `lastOkTs` null ⇒ ` · no sync on record`. Never `1970` or a raw ISO string.
- **Sentence, in this order, ` · ` joined, ellipsized:**
  1. `stalled` ⇒ the `capture` member's `reason` verbatim (`OBD feed stalled.`). Otherwise `all 4 feeds writing` (R3: OBD, light, IMU, UPS) while recording, or `not driving` while idle.
  2. **Away:** `wifi.home === false` ⇒ `away from home` (neutral; F-155 at-home sync). If `wifi.home` is null, no home word at all: never guess away.
  3. **Rows:** `sync.rowsWaiting` ⇒ `n rows waiting` (`fmtThousands`, so `12,345`). `sync.edrRowsWaiting` > 0 ⇒ `n event rows`. Zero event rows prints nothing.
     - `notCounted` is a **list of table names** (US-916: the snapshot tables, named, never folded into `rowsWaiting`). Non-empty ⇒ the count reads `12,345+ rows waiting`: the `+` sits on the number itself, so an ellipsis can never cut it off and leave a total that looks complete. The names are in the DATA detail (`not counted: <table>, <table>`). An empty list prints no `+`.
     - **Never fold them in and never imply zero:** `rowsWaiting` counts only the counted tables, so the words always say some tables weren't counted.
- **Sync failing at home** (no member until US-917): the sentence shows the provider's state, neutral, never amber. With no member, amber would break §4.0.
- **Old fields retired:** `rows` / `pending` no longer exist.

### 4.4 WIFI (carries US-732 + US-742; S3)
The provider publishes `wifi {state: up|weak|down|null, ssid, rssiDbm, home, ts}` + `source.wifi {available, reason: nmcli_absent|not_associated|read_failed}`. The shipped weak band is kept (Atlas 732-4). **The emitter derives `state`; the page applies no RSSI threshold.**

| Provider | Value | Colour | Sentence | Counted |
|---|---|---|---|---|
| `up`/`weak`, `home: true` | `home` | `--green-ok` | `<ssid> · good signal` / `· weak signal` | no |
| `up`/`weak`, `home: false` | `other network` | `--text-secondary` | same | no |
| `up`/`weak`, `home: null` | `connected` | `--text-secondary` | same | no |
| `down` (`not_associated`) | `down` | `--text-tertiary` | `not connected` | no |
| `null`, no reason | `--` | `--text-tertiary` | `not read yet` | no |
| `null`, `nmcli_absent` | `--` | `--text-tertiary` | `no WiFi tool on this host` | no (dev box never counts, Atlas) |
| `null`, `read_failed` | `? not read` | `--amber-warn` | the `wifi` member's `reason` (`WiFi couldn't be read.`) | **yes** |

- **`weak` is never amber, anywhere** (§4.0): it's a band on a working link, and it isn't counted.
  - 🔴 **Code change owed:** shipped `wifiGlyphState` maps `weak → "amber"`. US-894 makes it `weak → "neutral"` (the `--text-secondary` glyph). The strength word lives in the sentence, and the dBm in the detail.
- **`up` reads `good signal`, not `strong`.** `up` only means "above the weak band", and `strong` would claim more than that.
- **Unknown is never `down`** (Atlas 2026-08-20). **`--` is the one no-data mark** (two hyphens, as on the Warnings icon), never `—`.
- **Top-bar WiFi glyph:**
  - `null` ⇒ dim `--text-tertiary` arcs, **no slash** (a slash claims `down`);
  - `down` ⇒ the slashed glyph;
  - `read_failed` ⇒ amber, the one amber WiFi state.

### 4.5 UPS (S5)
- **Source:** `states/battery-health` (`vcellV`, `soc`, the health verdict, `ts`) for the cell. The **sensed** power source is `system-status.power.source` (`external` | `battery`, US-668), the field shipped `powerTile` reads. `system-status` carries no VCELL or SOC.
- **Value:** `4.12 V` (`vcellV`, 2 decimals as the shipped `vcellTile`).
  - `vcellV` null ⇒ `--`.
  - UPS source unavailable ⇒ `--` + the typed reason (`gauge unreadable`, as shipped).
- **Sentence:** `on external power` / `on battery` / `power source unknown`, then ` · <age>`, where age = `agoText(now, battery-health.ts)`.
  - **Spool 2026-10-19:** the source, the VCELL value and its age are information.
  - **Never `on car power` or `wall`** (CIO 2026-10-19). The shipped `powerTile` detail `wall/car power` retires with the card.
- **Colour:** value `--text-primary`, sentence `--text-secondary`.
  - **`on battery` is neutral, not amber.** There's no UPS member (§4.1), and the shipped `powerTile` `level: "amber"` for battery does not carry over (§4.0).
  - On battery is still the state a viewer can't infer from a lit screen, so the words say it.
- **Never on this row:** SOC (`≈ 92 %` is retired from the row; S-3), a runtime, `charging`, `crate` (registers absent on this silicon; shared MEMORY).
- **No wall-vs-car row** (carries US-729).

### 4.6 Detail screens (parked; Back returns to System)
| Detail | Contents |
|---|---|
| **OBD** | per layer: state, since when, last success `ts`, retry count; adapter MAC; the row's sentence in full |
| **DATA** | per feed (OBD, light, IMU, UPS): writing / silent + last row age; sync: last data stored (`lastOkTs`, local), rows waiting, event rows waiting, `not counted: <table>, <table>` (the `notCounted` names, verbatim), at-home state |
| **WIFI** | SSID, strength (word + `rssiDbm` dBm), home network yes / no / unknown, the typed `source.wifi.reason` in words. ~~IP~~ (no field) |
| **UPS** (replaces the Battery Health card; S6) | below |
| **Pi** (from the verdict line) | below |

#### 4.6.1 UPS detail (S5 + S6)
**The Battery Health card retires (CIO).** Its content moves here, with its existing rules (US-401 F-8–F-11, US-504, US-736, ARCH-065) and its existing view functions:
- **VCELL** (`vcellTile`) and the **source** with its age.
- **Health verdict:** `GOOD` / `DEGRADED` / `REPLACE` / `--` (`healthValue`), **never alarm-red, never amber** (Spool, load-bearing; `healthLevel` as shipped: green for good, neutral otherwise).
  - It's followed by the unknown reason (`BATTERY_HEALTH_REASON_TEXT`) or the T-vs-J margin (`healthMarginText`, e.g. `11 min vs 40 s job`), and **always** the F-9 `last health check · <date> (<age>)` line.
  - The margin is the verdict's evidence, not a runtime: it says how long to the reserve floor against the at-home job, and it appears only under a resolved verdict.
- **SOC:** `≈ 92 % (modelled)`, only when `soc` is a real number (F-8), `--text-secondary`, last in the list. It's never a readiness signal (Spool) and never on the row.
- **Label:** `Pi UPS battery` (F-11: never vehicle/car battery).
- **Dropped:**
  - the drain ladder and **`~N min to cutoff`** (a banned runtime: the pack capacity is unmeasured);
  - **pack epoch** and **voltage trend**: no field exists. Hard-coding `4×18650 since 2026-09-26` into the page would be a fact that goes stale silently. If the CIO wants either back, the provider publishes it first.
  - `restedHistory` stays unrendered until Spool says what a reader should take from it.

#### 4.6.2 Pi detail (S7)
- **CPU temperature:** `cpuTempC` at its 0.1 °C as read, with `limit 80 °C` beside it.
- **Throttling:** `throttled` now / since boot, in words + `throttledHex`.
- **Disk:** `diskFreeBytes` in GiB, floored to 0.1, with `limit 20 GiB` (`diskThresholdBytes`).
- **Uptime:** `uptimeS` as `3 h 2 min`.
- **Version.**
- Each limit in `pi.overLimit` is named in amber, and **only those** (§4.0).
- **Version (S7, confirmed):** the same string as the top-bar `#version-chip`, from `.deploy-version` through its ONE existing reader (Atlas P8). It's **not** in the `pi` block, and the page never reads it a second way.

### 4.7 Settings (F-126, now in V0.30; S9)
Reached from **SETTINGS ›** on System and from the **⋮** overlay band, **parked or not** (§4.7.2). The ⋮ is never hidden (S-13). That replaces the 2026-10-15 note "⋮ is hidden while moving".

| Setting | Control | Key | Apply tag |
|---|---|---|---|
| Brightness (US-878-c) | `AUTO` \| `FIXED` segmented, then a `− nn % +` stepper shown only when FIXED | Atlas names the key(s) | the shipped tag its consumer earns (see below) |
| Auto-dim ends (dim-start, full-bright) | two lux steppers on a **1-2-3-5 ladder** (… 1 · 2 · 3 · 5 · 10 · 20 · 30 · 50 · 100 · 200 · 300 · 500 …), whose ends **cannot cross** | `pi.display.autoDim.luxMin` / `luxFull` (now in `OVERRIDABLE_KEYS`, Atlas) | the tag its consumer earns (Atlas; `autoDim` is re-read on mtime change, US-878-b) |
| Auto-rotate pages | stepper `OFF · 5 · 8 · 10 · 15 · 30 s` | `pi.display.carousel.autoRotateS`, 0 = off (US-541-a) | `applies on reload` |
| Calibration mode | `Off` \| `On` | `pi.calibration.mode` | `applies on capture restart` |
| Auto-analyze after drive | `Off` \| `On` | `pi.analysis.triggerAfterDrive` | `applies on capture restart` |

- **Power mode: DROPPED** (CIO 2026-10-19). It was already deleted from `SETTINGS_SPECS` by US-668, and nothing returns.
- **Auto-dim ends: a setting** (CIO 2026-10-19 reversed Atlas ruling B; Atlas acked).
  - **What they set:** `luxMin` (dim-start) and `luxFull` (full-bright) are also the DAY/DUSK/NIGHT boundaries on the Light page.
  - **Steps:** each stepper moves to the next value on the 1-2-3-5 ladder. A stored value off the ladder (e.g. a hand-edited `4`) shows exactly as stored, and the next tap moves to the neighbouring ladder value.
  - **Ends cannot cross**, enforced twice:
    - **Page:** dim-start's `+` is disabled when its next step would be ≥ full-bright, and full-bright's `−` when its next step would be ≤ dim-start.
    - **Seam (Atlas):** `luxFull > luxMin` on the EFFECTIVE values, and a crossing POST returns **400**. A 400 is a rejected write: `couldn't save`, and the stepper snaps back to the re-read value (§4.7.1). The page guard is a convenience; the 400 is the rule.
- **Shipped words win (S9):**
  - **Apply tags:** the shipped `SETTINGS_APPLY_NOTES`, i.e. `applies on reload` / `applies on capture restart`.
    - My `applies now` / `next drive` / `after a restart` are retired. US-668 deleted `live`, and `test_noDeadApplyStatesAreLeftInTheMapping` fences it.
    - **Brightness takes whichever tag its consumer earns.** If the page re-reads the override on reload, it's `applies on reload`, and the band reloads after a confirmed save as auto-rotate does (US-533 B1).
    - A new `live` note comes back only with a consumer that re-reads per cycle, and with the test. Atlas's call.
  - **Status:** the shipped `saving…` / `saved` / `couldn't save`. My `stored: …` / `kept …` are retired: the control itself shows the stored value, and a rejected write snaps the control back to it.
- **Auto-rotate (S9):** the stepper is the CIO-approved design (2026-10-13). The shipped Off/On (on writes `CAROUSEL_DEFAULTS.autoRotateS`, 8 s) is its two-value subset, and the key and the 0 = off rule are unchanged.
  - **The stepper writes the chosen seconds through the same key.** It needs no new contract, only `kind: "seconds"` getting a stepper instead of `settingsChoices`.
  - **In S110** (CIO-approved design; Atlas A8 OK).
- **Brightness stepper (S9):**
  - **Floor = the EFFECTIVE `pi.display.autoDim.minLevel`** (Atlas A5, the US-627 coupling), never a literal. Shipped config is 0.75, so FIXED runs **75–100 %**.
    - There's no separate 20 % floor: that was my unsourced 10-13 default, and it's withdrawn.
    - If `minLevel` is off the 5 % grid, the lowest step is `minLevel` itself, then the next multiple of 5.
    - If the effective `minLevel` can't be read, the FIXED stepper is disabled and reads `Unknown`. A guessed floor would be a fabricated one.
  - **Step:** 5 % (my operator choice, kept).
  - **STOP still wins:** a STOP takeover forces full brightness regardless (`brightnessAlarmActive`), so an alarm is never dimmed by the override.
  - **CIO judgement in the car (AC 12)** still decides whether the floor is right. A different floor is a `minLevel` change, not a second number.
- **Each change saves on its own** (CIO); there's no Save button.
- The Light page shortcut opens Settings **scrolled to Brightness**.
- A footer line points to the ⋮ menu for service controls; they never appear in Settings.

**Visual design (CIO-approved 2026-10-13; mockup https://claude.ai/artifact/Vfsd6VugUGfoQAMYJZPo6R, `proposals/2026-10-13-v030-settings-screen.html`):**
- **Top bar:** `‹ BACK` (left) · clock · `SETTINGS` (page-name slot).
- **Two sections**, headed in `--accent`:
  - **DISPLAY:** brightness, auto-dim range, rotate pages;
  - **SYSTEM:** calibration mode, analyze each drive.
- **Rows are stacked:** name + apply tag; description; control; status. **Setting names are upper case**, since the Michroma subset has no lower case.
- **Controls:** steppers `− value +` with 40 px targets (brightness, the two lux ends, rotate pages); segmented choices for `AUTO|FIXED`; switches for the two booleans.

One list, which **scrolls with a visible scrollbar** if it's taller than the panel (no silent clip).

#### 4.7.1 Honest write (unchanged from W-18)
- **Shown value:** each control shows the real stored value. Unknown selects nothing and reads `Unknown`, never `Off`.
- **On tap:** `saving…`, then confirm **from the re-read** (`settingsSaveResult`), or snap back + `couldn't save`. Never optimistic success.
- **Service controls:** the destructive service controls stay in their own band below, with confirms (unchanged).

#### 4.7.2 Locked until parked (S-13; S9)
The lock is `engineParked.parked === false`, the ONE US-511 debounce: **parked = engine OFF held 8 s** (Atlas A7, CIO accepted). Never a second test.
- ⚠️ **The lock is not "moving".** It also locks a stationary car with the engine idling, and for 8 s after the engine stops, so no word on the glass may say `moving`.
- **The band stays visible and readable while locked.** Every value shows its real stored value, as parked.
- **Every control is locked:**
  - `--text-tertiary` ink, no fill on the active segment (the active one keeps a `--text-tertiary` outline so the stored value is still readable);
  - no pointer, and steppers show no `−` / `+`;
  - a tap does nothing: no write, no `saving…`.
- **One line at the top of the band**, mono `--fs-meta`, `--text-secondary`: **`🔒 view only — engine off to change`** (34 characters, 307.0 px).
  - It's an instruction, so it's true in every locked state: idling at the kerb, driving, and the 8 s hold. `engine on — view only` would be false during the hold; `car is moving` is false whenever the car is idling.
  - It's not Michroma: it has lower case, `—` and `🔒`.
  - Apply tags and status lines stay as they are.
- **A write in flight when the lock engages finishes honestly:** its re-read still confirms or snaps back. Locking must never abandon a write mid-way and leave `saving…` on the glass.
- **Parking unlocks** on the same debounce, with no reload.
- **SETTINGS › on System** follows the same rule. It's always shown and opens the locked view while not parked, because it only navigates (R5 holds, like the Warnings icon).
- **System row taps** (details) stay **parked-only** as before.
- The service band's own rules are US-659's and unchanged.

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| Verdict | `system-status.verdict {issueCount, members[{key, reason}]}` | **S109 US-877-b** (bt, adapter, capture, wifi, pi) | Atlas / Ralph |
| Link per layer | `system-status.link.{bt, adapter, ecu}` state + `available` + `ts` | **S109 US-876-*** | Atlas / Ralph |
| Capture per feed | `capture-health.feeds` | exists (US-688) | — |
| Sync | `system-status.sync {lastOkTs, rowsWaiting, edrRowsWaiting, notCounted}` | **S109 US-916** | Atlas / Ralph |
| WiFi | `system-status.wifi {state, ssid, rssiDbm, home, ts}` + `source.wifi {available, reason}` | **S109 US-732** | Atlas / Ralph |
| UPS cell | `states/battery-health` (`vcellV`, `soc`, health verdict + reasons + margin, `ts`) | exists | — |
| Power source | `system-status.power.source` (`external` \| `battery`) | exists (US-668) | — |
| Pi health | `system-status.pi {cpuTempC, throttled, throttledHex, throttledSinceBoot, diskFreeBytes, diskThresholdBytes, diskVerdict, uptimeS, overLimit[], ts}` | **S109 US-877-a** | Atlas / Ralph |
| Version | `.deploy-version` via the `#version-chip` reader | exists (Atlas P8) | — |
| Settings | `/settings` overlay (`OVERRIDABLE_KEYS`), re-read on write | exists; **brightness key(s) new, US-878-c**; **`autoDim.luxMin` / `luxFull` join `OVERRIDABLE_KEYS`** with the cross-key rule `luxFull > luxMin` on effective values (POST 400) | Atlas |
| Issue counting | the verdict | **provider-derived** (Atlas 08-20 rule) | Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. **ARCH-061 fixture** (BT + adapter up, ECU silent):
   - chain `g g n`;
   - the sentence is `ECU not answering (key off?)`;
   - the verdict is **not** incremented;
   - the top bar shows the 3 dots;
   - **no element reads "Bluetooth down"**.
3. **Connecting fixture:** BT step neutral, `Bluetooth connecting… (takes ~1 min)`, verdict **not** incremented. **Retrying fixture:** BT step amber, verdict incremented, sentence = the `bt` member's `reason` verbatim.
4. **ARCH-062:**
   - A previous-session ECU success with this session silent renders grey, never green.
   - A `null` layer renders a **dashed** step (and a hollow top-bar dot), never the solid `down` look.
5. **WiFi:**
   - `null` with no reason or `nmcli_absent` renders `--`, uncounted, never `down`;
   - `read_failed` renders `? not read` amber and counted;
   - `weak` is never amber, on the row or the glyph.
6. **UPS:**
   - never renders a runtime, `charging`, `crate`, SOC on the row, `car` or `wall`;
   - `on battery` is not amber;
   - no `min to cutoff` anywhere on the page or its details.
7. **🔴 The amber set equals the member set:** every amber element maps to exactly one `verdict.members[].key`, and every member has one (US-759). Assert it on every fixture.
8. **While not parked** (engine on, or off < 8 s; test both an idling-stationary and a driving fixture):
   - row taps open nothing;
   - SETTINGS › and ⋮ open the Settings band locked;
   - no control writes;
   - `🔒 view only — engine off to change` is present, and no element on the page says `moving`.
   - **In-flight write:** one in flight across the transition still ends in `saved` or `couldn't save`.
9. **Settings:**
   - a rejected write snaps back with `couldn't save`;
   - the success state shows the re-read value;
   - the apply tags are exactly the shipped `SETTINGS_APPLY_NOTES` values;
   - no power-mode row exists;
   - the auto-dim ends cannot cross: the page guard disables the crossing step, and a crossing write that reaches the seam gets a 400, shows `couldn't save` and snaps back;
   - the FIXED floor equals the effective `minLevel` (75 % on shipped config), and no literal floor exists in carousel.js.
10. Long row text ellipsizes on one line (no wrap overflow, no clip).
11. No literal colour or px in this page's CSS. The chain SVG uses relative units only.
12. **DoD (R15): CIO judgement in the car,** including whether the `minLevel` floor is right.
13. **Words:** every member sentence on the page is the provider's `reason` byte for byte. `carousel.js` contains none of the S109 reason strings (a file-wide grep gate, as US-899's `PULL OVER` one).
14. **Top bar:** the left cluster with the chain fits its 168.6 px side track, by `test_topbar_three_column_grid`'s measured model.

## 7. Fixtures (S10)
Each is a `system-status` (+ `capture-health`, + `battery-health` where named) payload, regenerated from the real builders (Atlas L7), never hand-typed.

| Fixture | Exercises |
|---|---|
| `arch061-key-off-home` | AC 2: BT + adapter up, ECU down, home, `ALL OK` |
| `all-ok-driving` | all `up`, recording, home, external power |
| `bt-connecting` | AC 3, neutral, uncounted |
| `bt-retrying` | AC 3, `bt` member, `1 ISSUE`, reason verbatim |
| `adapter-silent` | `adapter` member, amber sentence |
| `link-not-read` | every layer `null`: dashed steps, hollow dots, `not read yet` |
| `prev-session-ecu-stale` | AC 4 |
| `capture-stalled` | `capture` member, value `stalled`, reason verbatim |
| `away-from-home` | `wifi.home false`, `away from home`, rows waiting, uncounted |
| `rows-not-counted` | `notCounted: ["<table>", "<table>"]` ⇒ `12,345+ rows waiting` on the row, the names in the detail, never folded into the count |
| `wifi-weak-home` | `home` green, `weak signal`, glyph neutral |
| `wifi-not-read` | `null`, no reason ⇒ `--`, uncounted |
| `wifi-nmcli-absent` | dev box ⇒ `--`, `no WiFi tool on this host`, uncounted |
| `wifi-read-failed` | `wifi` member ⇒ `? not read` amber |
| `ups-on-battery` | `on battery` neutral, VCELL + age, no SOC on the row |
| `ups-gauge-unreadable` | typed NA |
| `pi-hot` | `pi` member, one limit, the Pi line |
| `pi-multi-limit` | `Over limit: CPU temp, throttling, disk.` |
| `two-issues` | `bt` + `pi`: `2 ISSUES`, the amber set equals the member set |
| `verdict-absent` | `--`, never `ALL OK` |
| `settings-write-rejected` | AC 9 |
| `settings-lux-cross-rejected` | AC 9: a crossing write gets a 400 ⇒ `couldn't save`, snap back |
| `settings-floor-from-minlevel` | AC 9: FIXED floor = effective `minLevel` (0.75 ⇒ 75 %); `minLevel` unreadable ⇒ FIXED disabled, `Unknown` |
| `settings-locked-idling` | AC 8: stationary, engine on |
| `settings-locked-driving` | AC 8, incl. one in-flight write |

**Retired:** `ups-low`. There's no UPS member (Spool + Atlas P5), so the fixture had no basis.

## 8. Out of scope
- detecting wall vs car power (US-729);
- battery runtime (capacity unmeasured);
- managing networks (Atlas WiFi ruling: display only);
- the audio alerts setting (US-538, deferred);
- the sync verdict member (US-917).

## 9. Open items
- **Atlas:**
  - the brightness override key(s) and the apply tags for brightness and auto-dim (US-878-c);
  - whether `restedHistory` is ever reader-facing (with Spool).
- **CIO:**
  - whether the effective `minLevel` floor is right, in the car.
- **Marcus:** ARCH-061 + US-713 close through this design.

## 10. Mockup gaps (the spec wins)
Both System mockups (2026-10-12, OEM 2026-10-15) and the Settings mockup (2026-10-13) predate this fold. **Where they differ, this spec wins:**
- **UPS row:**
  - shows `≈ 92 %` and `on car power`. It's now `4.12 V` + `on external power · 12 s ago`;
  - the UPS detail shows pack epoch and trend (dropped), and lacks the health verdict (added).
- **WiFi:** the weak glyph is amber (now neutral); `? not read` shows for every unread state (now `--` unless `read_failed`); it says `strong` (now `good signal`).
- **OBD:** no `null` (dashed) step; old sentences (now the member reasons).
- **Settings:**
  - a power-source row (gone);
  - a 20 % brightness floor (now the effective `minLevel`);
  - the apply tags `applies now / next drive / after a restart` and status `stored: … / kept …` (now the shipped words);
  - no locked state.
- **⋮:** shown hidden while moving (now always visible).

The mockups can be brought up on a later lease. Nothing in S110's build reads them.
