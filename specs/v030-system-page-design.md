# V0.30 System page (+ detail screens + Settings) — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12). **S110 fold 2026-10-19 (UIDEV-007):**
- the CIO's rulings of 2026-10-19 (UPS row, power mode, ⋮ while not parked, brightness, and auto-dim ends settable; Marcus C1–C4 corrections and the S110 draft's I1–I13 gaps folded the same day);
- the S109 providers as groomed (verdict members, per-layer link, WiFi, sync, Pi health);
- my S109 words;
- the shipped Settings band, whose words win.

Per-id answers to Marcus: S1–S10. Where this spec and an older note disagree, this spec wins.

**Mockup:** **`specs/v030-system-page-oem.html` (v2, 2026-10-22, UIDEV-010) is current: System, details and Settings, brought up to this spec** (§10). Layout A is the locked one, as first drawn in `proposals/2026-10-12-v030-system-page.html` (https://claude.ai/artifact/47FkWPp39fVQL3ciKph8ra). The 2026-10-15 OEM artifact (https://claude.ai/artifact/XXpv3Qn3vUzJj7j4TJfF74) predates the S110 fold.

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
| S-13 | ⋮ while not parked (CIO 2026-10-19, US-659) | **The ⋮ stays visible and openable while driving.** Its Settings band stays, and **every control is locked read-only until parked**: gear `P` or `N`, held 8 s (CIO 2026-10-22; §4.7.2) |

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
- **Every row is ≥ 44 px tall** (a touch target when parked), through a new token **`--row-min: 44px`** in the `dashboard.css` token block beside `--tap-min: 40px` (I10). No literal px in the page's CSS.
- **Long text ellipsizes on one line**, and the full text is in the row's detail. That's no silent clip: the ellipsis is the visible sign.

## 4. Behaviour

### 4.0 The colour rule (🔴 load-bearing)
**Amber means counted, and counted means amber.** Every amber element is a member of the verdict count, and every counted member shows amber somewhere on the page (AC 7). An amber row under `ALL OK` is a false instrument.
- **Expected states are neutral and uncounted:**
  - Bluetooth trying to link, at key-on and for hours on a parked key-off car (Atlas S110 G1);
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
| `sensor` *(S113, US-869-c; Atlas may rename the key)* | `capture-health.feeds.<imu\|light\|ups>.state` = `faulted` (Atlas B2): **one member per faulted feed**, in `FEED_NAMES` order, each carrying **`feed`** (`imu` / `light` / `ups`). Clears when the feed recovers | DATA row: sentence, **one span per member**; the feed's line in the DATA detail. Each amber element carries `data-member="sensor"` **and** `data-feed`, so A5's one-element-to-one-member check holds with two `sensor` members |
| `wifi` | the WiFi read **failed** (`reason: read_failed`) | WIFI row: `? not read` |
| `pi` | `pi.overLimit` non-empty | the Pi line under the verdict |

- **Not members (S109):**
  - **`sync`:** banked as US-917, with my sync words in its goal. Until it lands, a sync failing at home is **shown, never counted**. The DATA sentence says it, neutral.
  - **UPS:** no grounded band (Spool + Atlas P5).
  - ECU silent (S-10), away from home, WiFi down, WiFi weak, WiFi not read for want of a tool (`nmcli_absent`), and any null.
- **The Pi line** shows only when `pi` is a member. It's one mono `--fs-meta` line in amber under the verdict, carrying the member's `reason` verbatim, e.g. `CPU 80.2 °C, limit 80 °C.`. Tap it (parked) ⇒ **Pi health** detail.
  - **` ›` (I9):** a space + U+203A, appended **only while parked**, when the tap works. While not parked the tap does nothing, so no `›`: a chevron that leads nowhere is the US-758 failure.
- **No verdict** (`verdict` absent or the file unreadable): the value is `--` in `--text-tertiary`, never `ALL OK`. `ALL OK` is the provider's claim that it looked.

### 4.2 OBD chain (S2)
The provider publishes a state per layer (`link.bt`, `link.adapter`, `link.ecu`): `up` / `connecting` / `retrying` / `down` / `null`, each with `available` + `ts` for **this session** (ARCH-062).

| Layer state | Step look | Counted |
|---|---|---|
| `up` | `--green-ok` outlined step | no |
| `connecting` (not linked; an attempt is under way or due) | `--text-secondary`, neutral | no (CIO 2026-10-16; still closes US-713, because the step is visible and the sentence says what is happening) |
| `retrying` (was up this session, dropped) | `--amber-warn` **only on a member's layer**; otherwise `--text-secondary` (I2) | only `bt` |
| `down` | `--amber-warn` on a member's layer; otherwise `--text-tertiary`, solid outline | only if it's a member (`bt`, or `adapter` while BT is up) |
| `null` (not read this session) | `--text-tertiary`, **dashed** outline, label kept | never |

- **Amber is keyed to the member, never to the state (I2):** the BT step is amber only while `bt` is a member, and the ADAPTER step only while `adapter` is. A retrying ECU (never a member; after key-off it's the normal state, S109 G1) and an adapter down or retrying while BT is down (not a member: BT is the fault) are `--text-secondary` / `--text-tertiary`. **The top-bar dots follow the same rule.**
- `null` is new in this fold. It's the ARCH-062 rule as a look: a step we didn't read must not look like a step we read as down. **Dashed = no reading; solid = a reading.**
- **Sentence, one rule:**
  1. **If the row has a verdict member (`bt` or `adapter`), print that member's `reason` verbatim.** Those are the S109 words, e.g. `Link dropped. Retrying.` / `Not linked. Check the OBD dongle.` / `Bluetooth up; adapter not answering.` Then the Warnings entry and this row can never disagree, because they're one string.
  2. **Otherwise**, walk the layers in order **BT → ADAPTER → ECU** and take the **first layer whose state isn't `up`** (I1). Look its state up in this table; the layers after it don't speak. That's a lookup on a provider enum, not a comparison, the same pattern as `LIGHT_REASON_TEXT`:

| First non-up layer → state | Sentence | Note |
|---|---|---|
| bt `connecting` | `Bluetooth trying to link (key off?)` | **G1:** key off and parked, rfcomm releases after each failed attempt, so this is the steady state for hours (`n-n-n`). The old `(takes ~1 min)` was a promise that never comes true there, and it's **dropped everywhere**: the page can't know when a link will come. The words are true at key-on and on a parked car alike, and the `(key off?)` is the same honest guess as the ECU's |
| bt `down` / `retrying`, no member | `Bluetooth not linked` / `Bluetooth retrying…` | fallback only: the S109 rules make these a member |
| bt `null` | `Bluetooth not read yet` | covers "all null": later layers don't speak |
| adapter `connecting` | `adapter connecting…` | |
| adapter `down` / `retrying`, no member | `adapter not answering` / `adapter retrying…` | fallback only: with BT up, these are a member |
| adapter `null` | `adapter not read yet` | |
| ecu `connecting` | `ECU not answering (key off?)` | **G1:** with BT + adapter up, this is the parked car *during* an attempt (`g-g-n`). It takes the same words as `down` so the ARCH-061 fixture and the attempt read alike. Not Atlas's `not answering yet`, because `yet` promises an answer a parked car never gives |
| ecu `down` or `retrying` | `ECU not answering (key off?)` | never a member; retrying after key-off is normal (S109 G1) |
| ecu `null` | `ECU not read yet` | |
| all `up` | `ECU answering` | |

   - **An adapter fault while BT is down never speaks:** BT is the first non-up layer, so its member or row decides the sentence.

- **Retired as primary words:** `Bluetooth not linked` and `adapter not answering` survive only as the no-member fallbacks above. The member reasons replace them.
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
  - the capture state from **`capture-health`, never from the drive state** (I3 confirmed): `recording` / `idle` / `stalled` / `--` when capture-health is absent or its state is unknown (`--text-tertiary`).
    - **`stalled` if and only if there is a `capture` member** (Atlas A4, 2026-10-22: one source per fact). The member comes from `feeds.*.state` alone, and only with the ECU up (`system_status_emitter` :538-541), so the value and the count can never disagree in either direction. `stalled` is always amber.
    - **A top-level `stalled` with no member never reads `stalled` and adds no member** (corrected 2026-10-22, UIDEV-013; this replaces I3's grey `stalled`). The value comes from the top-level `reason`, in `--text-secondary`:
      - `never_written` (the logger has written no row since its process started, e.g. a cold boot) ⇒ `no rows`;
      - `stalled` (rows were written once; none inside the stall window) ⇒ `stopped`.
      - Both are no wider than `recording`, so ` · synced <when>` keeps the budget measured in UIDEV-010.
    - **A `sensor` member never changes the value** (UIDEV-014, S113): a faulted feed is not a stalled feed, so the row keeps `recording` / `idle` / … and only its sentence turns amber. `stalled` stays the `capture` member's alone (A4).
  - then ` · synced <when>` from `sync.lastOkTs` ("last data stored", S109 Rule 10), in local time (I3 date rule):
    - same local day ⇒ `fmtTimeOfDay` (`6:42 PM`);
    - the local day before ⇒ `yesterday`, **with no time on the row** (corrected 2026-10-22, UIDEV-010). `recording · synced yesterday 12:59 PM` is 37 characters = 445 px in the 334 px value column, so the ellipsis cut the time to a wrong-looking `5:0…`. That is the failure the `+` rule below exists to prevent. `recording · synced yesterday` is 28 characters and fits. The full `fmtStamp` is in the DATA detail;
    - older ⇒ `Oct 12` (month and padded day from the US-559 `STAMP_MONTHS`). The full `fmtStamp` is in the DATA detail;
    - a time with no date is only ever today's. A days-old sync must never read like this afternoon.
  - `lastOkTs` null ⇒ ` · no sync on record`. Never `1970` or a raw ISO string.
- **Sentence, in this order, ` · ` joined, ellipsized:**
  1. `stalled` with the member ⇒ the `capture` member's `reason` verbatim (`OBD feed stalled.`). Then **every `sensor` member's `reason` verbatim**, each in its own amber span, space-joined in `FEED_NAMES` order. The rest of this step still applies after them, **except `all 4 feeds writing`, which is never printed with a `sensor` member** (it would be false). Otherwise:
     - `all 4 feeds writing` (R3: OBD, light, IMU, UPS) while recording and no `sensor` member;
     - `not driving` while idle (I3 confirmed);
     - `capture not read yet` when the value is `--`;
     - **`no rows` / `stopped` (no member; W3):** a cause is named only from the fact that carries it (Atlas A4):
       - `link.ecu` is `down`, `retrying` or `connecting` ⇒ `ECU not answering`;
       - otherwise (ECU up, or the layer not read) no cause is printed. `no rows` ⇒ `no row logged this session`; `stopped` ⇒ `last row <age>` from the top-level `lastRowSecondsAgo` through `agoText` (a history age, `4 min ago`), and nothing when it's null.
       - Never `ECU not answering` with the ECU up: on a cold boot that would be false.
     - **The `sensor` reasons** (the provider writes them; the page prints them byte for byte, AC 13). Each is 23 characters or fewer, and uses the same words as the boot checklist (`v030-boot-shutdown-design.md` §1.3) and the Light page's `sensor_absent`:

       | Feed | `reason` code | Member `reason` |
       |---|---|---|
       | IMU | `sensor_absent` | `IMU sensor not found.` |
       | IMU | a read failure | `IMU read failed.` |
       | LIGHT | `sensor_absent` | `Light sensor not found.` |
       | LIGHT | a read failure | `Light read failed.` |
       | UPS | a read failure (its only fault: an I2C error; `0xFFFF` is not a fault, Atlas B1) | `UPS gauge read failed.` |
       | any | any other code | `IMU sensor fault.` / `Light sensor fault.` / `UPS gauge fault.` |
  2. **Away:** `wifi.home === false` ⇒ `away from home` (neutral; F-155 at-home sync). If `wifi.home` is null, no home word at all: never guess away.
  3. **Rows:** `sync.rowsWaiting` ⇒ `n rows waiting` (`fmtThousands`, so `12,345`). `sync.edrRowsWaiting` > 0 ⇒ `n event rows`. Zero event rows prints nothing.
     - **Singular (I3):** `1 row waiting`, `1 event row`. With the `+` it stays plural: `1+ rows waiting`.
     - **`rowsWaiting` null ⇒ `rows not read`**, never `0 rows waiting`. The same rule applies to a null `edrRowsWaiting`: nothing prints.
     - `notCounted` is a **list of table names** (US-916: the snapshot tables, named, never folded into `rowsWaiting`). Non-empty ⇒ the count reads `12,345+ rows waiting`: the `+` sits on the number itself, so an ellipsis can never cut it off and leave a total that looks complete. The names are in the DATA detail (`not counted: <table>, <table>`). An empty list prints no `+`.
     - **Never fold them in and never imply zero:** `rowsWaiting` counts only the counted tables, so the words always say some tables weren't counted.
- **Sync failing at home** (no member until US-917): the sentence shows the provider's state, neutral, never amber. With no member, amber would break §4.0.
- **Top-bar sync glyph (I4):** shipped `syncGlyphState` paints `sync.stale` amber with no member behind it. US-894 makes it **neutral** (`--text-secondary`). When US-917 lands a `sync` member, the glyph goes amber exactly while that member is present.
- **Old fields retired:** `rows` / `pending` no longer exist.

### 4.4 WIFI (carries US-732 + US-742; S3)
The provider publishes `wifi {state: up|weak|down|null, ssid, rssiDbm, home, ts}` + `source.wifi {available, reason: nmcli_absent|read_failed|not_read}` (`wifi_reader` :180-193 + the emitter's `REASON_WIFI_UNKNOWN`; there is no `not_associated`, Atlas A6). The shipped weak band is kept (Atlas 732-4). **The emitter derives `state`; the page applies no RSSI threshold.**

| Provider | Value | Colour | Sentence | Counted |
|---|---|---|---|---|
| `up`/`weak`, `home: true` | `home` | `--green-ok` | `<ssid> · good signal` / `· weak signal` | no |
| `up`/`weak`, `home: false` | `other network` | `--text-secondary` | same | no |
| `up`/`weak`, `home: null` | `connected` | `--text-secondary` | same | no |
| `null`, `available: true` (associated, `ssid` set, `rssiDbm` null) | the `home` word, as the three rows above | as above | `<ssid> · no signal level` | no |
| `down` (`available: true`, not associated) | `down` | `--text-tertiary` | `not connected` | no |
| `null`, `not_read` | `--` | `--text-tertiary` | `not read yet` | no |
| `null`, `nmcli_absent` | `--` | `--text-tertiary` | `no WiFi tool on this host` | no (dev box never counts, Atlas) |
| `null`, `read_failed` | `? not read` | `--amber-warn` | the `wifi` member's `reason` (`WiFi couldn't be read.`) | **yes** |

- **`weak` is never amber, anywhere** (§4.0): it's a band on a working link, and it isn't counted.
  - 🔴 **Code change owed:** shipped `wifiGlyphState` maps `weak → "amber"`. US-894 makes it `weak → "neutral"` (the `--text-secondary` glyph). The strength word lives in the sentence, and the dBm in the detail.
- **`up` reads `good signal`, not `strong`.** `up` only means "above the weak band", and `strong` would claim more than that.
- **Unknown is never `down`** (Atlas 2026-08-20). **`--` is the one no-data mark** (two hyphens, as on the Warnings icon), never `—`.
- **`home: null` ⇒ `connected`, neutral** (I5 confirmed). Never `home`, and never `other network`.
- **Not associated is a reading, not a reason** (Atlas A6, 2026-10-22, verified in `wifi_reader` :180-193): `available: true`, `state: down`, reason null. The page has no special case for it. *(This replaces I5's `null` + `not_associated`: Atlas's W3 vocabulary named a reason that was never built, and the shipped producer wins.)*
- **Associated, no signal level (W1):** `available: true` with `state: null` means wlan0 is on a network (the SSID is known) but `/proc/net/wireless` gave no level, so `deriveWifiState` can't band it (`system_status_emitter` :606-607).
  - It's never `down` (the car is connected) and never `not read yet` (the link was read).
  - The page tells it from an unread link by `source.wifi.available`, never by a missing `ssid`.
- **No literal twins (Atlas A6):** the page's reason strings are checked against `wifi_reader.WIFI_REASON_*` and `system_status_emitter.REASON_WIFI_UNKNOWN`.
- **Top-bar WiFi glyph:**
  - `null` (`not_read`, `nmcli_absent`, or associated with no level) ⇒ dim `--text-tertiary` arcs, **no slash** (a slash claims `down`, and lit arcs claim a level);
  - `down` ⇒ the slashed glyph;
  - `read_failed` ⇒ amber, the one amber WiFi state.

### 4.5 UPS (S5)
- **Source:** `states/battery-health` (`vcellV`, `soc`, the health verdict, `ts`) for the cell. The **sensed** power source is `system-status.power.source` (`external` | `battery`, US-668), the field shipped `powerTile` reads. `system-status` carries no VCELL or SOC.
- **Value:** `4.12 V` (`vcellV`, 2 decimals as the shipped `vcellTile`).
  - `vcellV` null ⇒ `--`.
  - UPS source unavailable ⇒ `--` + the typed reason (`gauge unreadable`, as shipped).
- **Sentence:** `on external power` / `on battery` / `power source unknown` (any other `power.source`, including unresolved; the typed `reasons.source` is in the UPS detail in words), then ` · <age>`.
  - **The age is a FRESHNESS age (I6), so it uses the S105 M7 rule, not `agoText`:** floor, clamp at 0, `N s ago`, cap `999+ s ago`. `agoText` says `just now` under 60 s, so `12 s ago` could never show. US-894 lifts the M7 rule out of `motionUpdatedCell` into one shared helper that Motion and this row both call, so there's one freshness vocabulary. An undated payload ⇒ no age.
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
| **OBD** | per layer, **this session only** (ARCH-062): state; since when (= the layer's `ts`, the transition time); last success (= `lastOkTs`, through `fmtStamp`; `--` when the layer hasn't been up this session, never a time from an earlier boot); the row's sentence in full. **No adapter MAC** (Atlas A3, 2026-10-22): no publish field exists (it lives only inside `bt_resilience`), and a display must not grow its own reader, so the line isn't drawn. `available` = `state != null` (S109 I4, 2026-10-22). **Retry count waits on a field:** S109 doesn't publish one, so the line isn't drawn (the same rule as I5's IP). |
| **DATA** | per feed (OBD, light, IMU, UPS): `writing` / `stalled` / `idle` / `--` (unknown), **or the `sensor` member's `reason` in amber when the feed is `faulted`** (S113) + last row age (`--` when undated) (I3); sync: last data stored (`lastOkTs` through `fmtStamp`, local, full date), rows waiting, event rows waiting, `not counted: <table>, <table>` (the `notCounted` names, verbatim), at-home state |
| **WIFI** | SSID, strength (word + `rssiDbm` dBm; `no signal level` and no dBm when associated with `rssiDbm` null), home network `yes` / `no` / `unknown`. `state: down` ⇒ `not connected to any network`. The typed `source.wifi.reason` in words: `not_read` ⇒ `not read yet`, `nmcli_absent` ⇒ `no WiFi tool on this host`, `read_failed` ⇒ the member's reason. **No IP:** there's no field, and the row isn't drawn (I5) |
| **UPS** (replaces the Battery Health card; S6) | below |
| **Pi** (from the verdict line) | below |

#### 4.6.1 UPS detail (S5 + S6)
**The Battery Health card retires (CIO).** Its content moves here, with its existing rules (US-401 F-8–F-11, US-504, US-736, ARCH-065) and its existing view functions:
- **VCELL** (`vcellTile`) and the **source** with its age (M7 rule). An unresolved source shows its typed `reasons.source` in words (W2; `card_state_emitter` :219-254, `POWER_SOURCE_UNKNOWN_REASONS`):

  | `reasons.source` | Words |
  |---|---|
  | `provider_absent` | `no power sensor running` |
  | `source_unreadable` | `power sensor unreadable` |
  | `read_failed` | `power sensor read failed` |

  - **Not `no UPS fitted`.** `provider_absent` means no power-source provider runs in this process: the bench, *or* hardware that never started. The car has the X1209 fitted, so that word would be false on a Pi whose sensor failed to start.
  - The words name the **sensor** (the power-loss line), not the UPS or the pack: none of the three says anything about the battery.
  - `source_unreadable` is the live Pi's state today (two services claim GPIO6, I-us628). The word names the fact, not that cause: the cause isn't published.
  - A reason outside the three prints no words, only `power source unknown`. The page checks its keys against `POWER_SOURCE_UNKNOWN_REASONS`, so it has no literal twins. All three are 24 characters or fewer.
- **Health verdict:** `GOOD` / `DEGRADED` / `REPLACE` / `--` (`healthValue`), **never alarm-red, never amber** (Spool, load-bearing; `healthLevel` as shipped: green for good, neutral otherwise).
  - It's followed by the unknown reason (`BATTERY_HEALTH_REASON_TEXT`) or the T-vs-J margin (`healthMarginText`, e.g. `11 min vs 40 s job`), and **always** the F-9 `last health check · <date> (<age>)` line.
  - **The margin is exempt from "never a runtime" (I6), on three conditions:** it's the verdict's evidence (minutes to the reserve floor against the at-home job, ARCH-065, shipped); it appears only here, only under a resolved verdict; and it's always printed with its `vs n s job` half, so it reads as a margin. It never goes on the row.
- **SOC (I6):** `≈ 92 % (modelled)` when `socCalibrated === true`, and `≈ 92 % (modelled, uncalibrated)` otherwise. The shipped `(uncalibrated)` caveat survives. Only when `soc` is a real number (F-8), `--text-secondary`, last in the list. It's never a readiness signal (Spool) and never on the row.
- **LAST STOP (I7):** the US-744 prior-shutdown verdict lives here, as one line, `LAST STOP  <word> · <age>`, through the shipped `priorShutdownTile` (words, ages and the `(clock unsynced)` mark unchanged; always neutral, because it's history). It belongs with the UPS because the UPS is what makes a shutdown graceful.
- **Label:** `Pi UPS battery` (F-11: never vehicle/car battery).
- **Dropped:**
  - the drain ladder and **`~N min to cutoff`** (a banned runtime: the pack capacity is unmeasured);
  - **pack epoch** and **voltage trend**: no field exists. Hard-coding `4×18650 since 2026-09-26` into the page would be a fact that goes stale silently. If the CIO wants either back, the provider publishes it first.
  - `restedHistory` stays unrendered until Spool says what a reader should take from it.

#### 4.6.2 Pi detail (S7)
- **CPU temperature:** `cpuTempC` at its 0.1 °C as read, with `limit 80 °C` beside it.
- **Throttling:** `throttled` now / since boot, in words + `throttledHex`.
- **Disk:** `diskFreeBytes` in GiB, floored to 0.1, with `limit 20 GiB` (`diskThresholdBytes`).
- **Uptime (I9):** `uptimeS` as a duration: under 60 s ⇒ `under 1 min`; under 1 h ⇒ `42 min`; under 1 day ⇒ `3 h 2 min`; then `2 days 3 h` (`1 day 3 h`). Null ⇒ `--`.
- **Version.**
- Each limit in `pi.overLimit` is named in amber, and **only those** (§4.0).
- **Where the details render (I8):** every detail screen renders in the one `#sys-detail` overlay. The `#version-chip` pinned inside it is shown **only in the Pi detail**.
- **Version (S7, confirmed):** the same string as the top-bar `#version-chip`, from `.deploy-version` through its ONE existing reader (Atlas P8). It's **not** in the `pi` block, and the page never reads it a second way.

#### 4.6.3 LAST UPDATED + the shared page-detail pattern (CIO 2026-10-27, UIDEV-017)
relay(CIO, in car 2026-10-27): *"have the bottom navigation called last updated systems and have a separate page for all the devices and when they were last updated versus having them each on their own screen."* **CIO ruled it IN V0.30** (via Marcus, 2026-10-27).

**Entry: `UPDATED ›` on the verdict line, left of `SETTINGS ›`.**
- Same style as `.sys-settings`: neutral link, `--fs-meta`, letter-spacing 0.06em.
- **Fit:** the widest verdict is `8 ISSUES`. The most members possible are bt, adapter, capture, 3 × sensor, wifi and pi, so the count is one digit: 8 × 22.5 = 180 px.
  - Add `UPDATED ›` (9 × 9.93 = 89.4) and `SETTINGS ›` (99.3), plus 2 × 13 gaps: **395 of 448**.
  - `LAST UPDATED ›` would leave 4 px, so the link says `UPDATED` and the detail's title says `LAST UPDATED`.
- The ` ›` and the tap follow the I9 / §4.7.2 parked rule, like every detail.

**The LAST UPDATED detail:** one line per device, in this fixed order: OBD, IMU, LIGHT, UPS, WIFI, SYNC.
- Each line is ≥ `--row-min`. The label is Michroma `--fs-label` in the 4.5em row column.
- The value is `--font-mono` `--fs-label`: `<age> · <time>`, e.g. `2 s ago · 9:20:14 PM`. The age follows the M7 rule; the time is local 12-hour, through `fmtStamp`.
- 6 × 44 = 264 of the 270 px detail body.
- **Sources: one reader each, and no new field.**
  - OBD, IMU, LIGHT, UPS: `capture-health.feeds.<feed>` last-row time. This is the same field the DATA detail's last-row age reads, so it isn't read twice: the DATA detail and this one share it.
  - SYNC: `sync.lastOkTs` (last data stored).
  - WIFI: the WiFi read's `ts`. ASK(Atlas): name the field.
- **Undated** ⇒ `--` (the DATA detail's undated rule). **Never coloured:** an age has no band. A faulted feed's reason stays on the DATA detail; this page only says *when*.
- **Per-page UPDATED items go:** Motion's UPDATED cell is the only one (`dashboard.html`, `motion-updated`; Motion §3a).
  - A value's own age (`2 s old` on O2, the UPS row's `12 s ago`, …) **stays**. That says how fresh the number beside it is (honest instrument), not when a device last spoke.

**The shared page-detail pattern** (Engine HISTORY, Fuel FUEL TRIM, Motion IMU, and this one):
- **Where it renders:** the one detail overlay (§4.6 I8 `#sys-detail`, or a sibling with the same rules; the element is Ralph's call). It is solid (the P-4 rule: a navigational overlay is a destination).
- **Header:** `‹ BACK` top left; the title in Michroma.
- **Body:** 320 − 34 − 2 × 8 = **270 px**. **No detail scrolls** (the CIO's no-scroll rule, applied here too); each detail's spec carries its height budget.
- **Opens only while parked.** The opener is either a `›` link (System) or the **detail button**.
- **The detail button:**
  - Michroma `--fs-label` label, ` ›` in mono, `--text-primary` text;
  - 1px `--text-secondary` border, radius `--radius`, padding 12 px each side, height `--tap-min`;
  - **no state colour.** It is a real control and looks like one, which is the button grammar used correctly (US-758 was a non-control that wore it);
  - while not parked: `visibility: hidden`, space kept.

### 4.7 Settings (F-126, now in V0.30; S9)
Reached from **SETTINGS ›** on System and from the **⋮** overlay band, **parked or not** (§4.7.2). The ⋮ is never hidden (S-13). That replaces the 2026-10-15 note "⋮ is hidden while moving".

| Setting | Control | Key | Apply tag |
|---|---|---|---|
| Brightness (US-878-c) | `AUTO` \| `FIXED` segmented, then a `− nn % +` stepper shown only when FIXED | `overrideLevel` (Atlas S110 B4) | **`applies on reload`** (Atlas B12: the applier reads it from the per-request blob on the reload the band triggers) |
| Auto-dim ends (dim-start, full-bright) | two lux steppers on a **1-2-3-5 ladder from 1 to 1000 lux** (1 · 2 · 3 · 5 · 10 · 20 · 30 · 50 · 100 · 200 · 300 · 500 · 1000), whose ends **cannot cross** | `pi.display.autoDim.luxMin` / `luxFull` (now in `OVERRIDABLE_KEYS`, Atlas) | **`applies at the next light reading`** (Atlas B12, a new `SETTINGS_APPLY_NOTES` entry: the bridge re-reads config on its next burst. It claims no time, because with no sensor nothing applies it) |
| Auto-rotate pages | stepper `Off · 5 s · 8 s · 10 s · 15 s · 30 s` | `pi.display.carousel.autoRotateS`, 0 = off (US-541-a) | `applies on reload` |
| Calibration mode | `Off` \| `On` | `pi.calibration.mode` | `applies on capture restart` |
| Auto-analyze after drive | `Off` \| `On` | `pi.analysis.triggerAfterDrive` | `applies on capture restart` |

- **Power mode: DROPPED** (CIO 2026-10-19). It was already deleted from `SETTINGS_SPECS` by US-668, and nothing returns.
- **Auto-dim ends: a setting** (CIO 2026-10-19 reversed Atlas ruling B; Atlas acked).
  - **What they set:** `luxMin` (dim-start) and `luxFull` (full-bright) are also the DAY/DUSK/NIGHT boundaries on the Light page.
  - **Bounds (I11):** 1 … 1000 lux. Twilight is ~3.4 lux and overcast daylight ~1000, and the shipped 3 / 300 sit inside. At an end, that end's `−` / `+` is hidden.
  - **Steps:** each stepper moves to the next value on the 1-2-3-5 ladder. A stored value off the ladder (e.g. a hand-edited `4`) shows exactly as stored, and **the next tap moves to the neighbouring ladder value in the tap's direction** (`4`: `+` ⇒ 5, `−` ⇒ 3).
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
  - **Case (I11):** `Off`, mono, matching the switches' `Off` / `On`, then `5 s` … `30 s`. Not Michroma `OFF`: values are mono on this screen.
  - **Off-step values (I11):** a stored value off the steps (e.g. `12`) shows as stored (`12 s`). The next tap moves to the neighbouring step in the tap's direction (`+` ⇒ 15, `−` ⇒ 10). `−` from `5 s` ⇒ `Off`.
- **Brightness stepper (S9):**
  - **Floor = the EFFECTIVE `pi.display.autoDim.minLevel`** (Atlas A5, the US-627 coupling), never a literal. Shipped config is 0.75, so FIXED runs **75–100 %**.
    - There's no separate 20 % floor: that was my unsourced 10-13 default, and it's withdrawn.
    - If `minLevel` is off the 5 % grid, the lowest step is `minLevel` itself, then the next multiple of 5.
    - If the effective `minLevel` can't be read, the FIXED stepper is disabled and reads `Unknown`. A guessed floor would be a fabricated one.
  - **Step:** 5 % (my operator choice, kept).
  - **AUTO → FIXED first value (I11):** the level the screen is applying right now (`appliedBrightness().level`), rounded to the nearest 5 % and clamped to [effective `minLevel`, 100 %]. Switching mode never jumps the panel. If the applied level isn't known, use 100 %.
  - **Light page status while FIXED (I12, Atlas A5's `fixed` basis):** `BRIGHTNESS 80 % (fixed in Settings)`. It says where to undo it, in `--text-secondary`, never amber (an override is a choice, not a fault). It replaces the `(default, no reading)` that `lightStatusView` would print for an unknown basis today. The Light spec's "override (amber)" note is superseded, and folds on the next Light lease.
  - **STOP still wins:** a STOP takeover forces full brightness regardless (`brightnessAlarmActive`), so an alarm is never dimmed by the override.
  - **CIO judgement in the car (AC 12)** still decides whether the floor is right. A different floor is a `minLevel` change, not a second number.
- **Each change saves on its own** (CIO); there's no Save button.
- ~~The Light page shortcut opens Settings scrolled to Brightness.~~ **Banked, not S110** (I13, Marcus's default accepted).
- A footer line points to the ⋮ menu for service controls; they never appear in Settings.

**Visual design (CIO-approved 2026-10-13; mockup https://claude.ai/artifact/Vfsd6VugUGfoQAMYJZPo6R, `proposals/2026-10-13-v030-settings-screen.html`):**
- **Top bar:** `‹ BACK` (left) · clock · `SETTINGS` (page-name slot).
- **Two sections**, headed in `--accent`:
  - **DISPLAY:** brightness, auto-dim range, rotate pages;
  - **SYSTEM:** calibration mode, analyze each drive.
- **Rows are stacked:** name + apply tag; description; control; status. **Setting names are upper case**, since the Michroma subset has no lower case.
  - **A long apply tag drops to its own line; it never clips.** `AUTO-DIM RANGE` (Michroma) plus `applies at the next light reading` (33 characters = 298 px mono at `--fs-meta`) is wider than the row (UIDEV-010, measured on the v2 mockup).
  - **Descriptions fit on one line**, about 45 characters at `--fs-meta`. The v2 mockup's: `AUTO follows the sensor. FIXED holds a level.` · `dim below, full above; also DAY / DUSK / NIGHT` · `cycle pages; Off keeps the page you chose` · `log every reading for a calibration session` · `send each drive for analysis after it syncs`.
- **Controls:** steppers `− value +` with 40 px targets (brightness, the two lux ends, rotate pages); segmented choices for `AUTO|FIXED`; switches for the two booleans.

One list, which **scrolls with a visible scrollbar** if it's taller than the panel (no silent clip).

**In S110 (I13, Marcus's defaults accepted):** the DISPLAY / SYSTEM sections, upper-case names, 40 px targets (US-895-a); the visible scrollbar; `‹ BACK` and `SETTINGS` in the top bar. Banked: the Light-page shortcut.

#### 4.7.1 Honest write (unchanged from W-18)
- **Shown value:** each control shows the real stored value. Unknown selects nothing and reads `Unknown`, never `Off`.
- **On tap:** `saving…`, then confirm **from the re-read** (`settingsSaveResult`), or snap back + `couldn't save`. Never optimistic success.
- **Service controls:** the destructive service controls stay in their own band below, with confirms (unchanged).

#### 4.7.2 Locked until parked (S-13; S9) — the ONE parked rule for every parked-only control
**Parked = the derived gear fact** (CIO RULED 2026-10-22, UIDEV-011; *"P or N, same as everything"*):
- **Raw parked** = `states/gear` has `available === true` **and** `gear` is `"P"` or `"N"`. Strict string compare. A numbered gear is not parked.
  - `N` is published only when RPM > 0 **and** SPEED == 0 on fresh readings (`gear_derivation.py`, US-687-a), so a car stopped with the engine idling is parked.
  - `P` is published only on **fresh RPM 0 and fresh SPEED 0** (US-687-b, as amended by US-511-a: see the next line). The older path, RPM unusable on a healthy link past `parkDwellSec`, can no longer publish `P`: with RPM unusable there is no fresh SPEED 0 either.
  - **`P` and `N` both mean stopped** (Spool proposed, Atlas concurred 2026-10-22). `N` already requires SPEED == 0. The deriver's `P` branch now requires a fresh SPEED == 0 as well; that is a `gear_derivation.py` change, not on dev yet. So a rolling engine-off (fresh RPM 0, fresh SPEED > 0) publishes the deriver's absence with reason **`engine_off_rolling`**, not `P`, and the lock line reads `gear unknown`. The gear tile's reason text for it is **`engine off`** (10 characters, distinct from every other `GEAR_REASON_TEXT`; S112 I2, Marcus's default accepted). Spool: worth showing, because on this car a rolling engine-off loses power-steering assist and runs the brake-booster vacuum down. The words say what the token says and nothing more: not `stalled` (the cause isn't known) and not a warning colour (no band was ruled). **The parked rule stays exactly "gear `P` or `N`"; no page adds a speed term.**
- **Debounce:** the ONE US-511 hysteresis, kept as is: **8 s of raw parked turns it on, 3 s of raw not-parked turns it off.** Its input changes from `system-status.idle` to the gear fact; nothing else about it changes.
- **Any absence = not parked (fails closed):** no `states/gear`, `available` false or missing, any `reason` (`link_down`, `settling_park`, `stale`, `no_data`, …), an unreadable clock. Absence of the fact is never the fact.
- **One rule, every parked-only control:** this Settings band, System row taps, the Light shortcut, the Engine MIL link, and on Warnings the code-row tap, the Clear button and the key-on CODE ALERT. No page keeps a second test, and no page reads speed, RPM or `idle` to decide parked.
  - **The one exception is not a page-side test:** the Fuel SINCE RESET hold follows the provider's `resetAllowed` (Fuel §4.3; Atlas C1–C3, S112 I4). That gate is RAW gear `P`/`N` with no hold, **or** fresh SPEED ≤ 8 km/h, computed once in the orchestrator. Its refusal words are `slow to reset` / `speed unknown`.
- **Replaces** "parked = engine OFF held 8 s" (Atlas A7). That rule's input was `system-status.idle`, which means "never connected this boot", so after the first connect parked never returned until restart (Atlas US-407 b0; F2 confirmed on the car 2026-10-22: the P0443 row tap did nothing at KOEO while `states/gear` read `P`).
- ⚠️ **Known consequence, as ruled (Atlas confirmed 2026-10-22: `settling_park` is not parked, whatever the prior state; on car power the Pi has shut down ~9–10 s after key-off, before the unlock could matter):** **after key-off, `P` no longer publishes at all** (corrected 2026-10-22, S112 I3; the earlier text said `settling_park` then `P`, true only before `P` needed a fresh SPEED 0). After key-off the ECU goes silent, so RPM and SPEED both go stale. The gear tile shows the deriver's absence (`reading stale` or `no link`), and the parked-only controls lock with `gear unknown` 3 s after key-off and stay locked. On car power that lasts until shutdown, ~9–10 s later. On wall power (bench) it lasts until the next key-on, where KOEO's fresh RPM 0 / SPEED 0 publishes `P` and the band unlocks 8 s later. That's true and fails closed; not the page's to smooth over.
- ⚠️ **The lock is not "moving".** It also locks during the 8 s hold and whenever the gear is unknown, so no word on the glass may say `moving`.
- **The band stays visible and readable while locked.** Every value shows its real stored value, as parked.
- **Every control is locked:**
  - `--text-tertiary` ink, no fill on the active segment (the active one keeps a `--text-tertiary` outline so the stored value is still readable);
  - no pointer, and steppers show no `−` / `+`;
  - a tap does nothing: no write, no `saving…`.
- **One line at the top of the band**, mono `--fs-meta`, `--text-secondary`. The word follows the CURRENT raw gear reading, not the debounced state:
  - gear known and not parked (a numbered gear), or in the 8 s hold: **`🔒 view only — stop to change`** (29 characters, ≈ 262 px). It's an instruction and it's true: stopping gives `N` (or `P` with the engine off), and the hold then unlocks it. *Replaces `engine off to change` (2026-10-19), which became false: under the gear rule an idling car at rest unlocks.*
  - gear **unknown** (any absence above): **`🔒 view only — gear unknown`** (27 characters, ≈ 244 px). Not an instruction, on purpose: while the gear is unknown no driver action is sure to unlock it (a dead link stays dead when the car stops), so the line names the missing fact instead of promising an unlock. *(Atlas's US-407 b0 ASK: "a word for parked unknown". This is it.)*
  - Widths are computed, not measured: mono at 15 px is 9.03 px per character, taken off the measured 34-character `engine off to change` line (307.0 px) they replace. Both are shorter than that line, so both fit wherever it fit.
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
| Verdict | `system-status.verdict {issueCount, members[{key, reason}]}` | **S109 US-877-b** (bt, adapter, capture, wifi, pi); **`sensor` in S113 US-869-c** | Atlas / Ralph |
| Link per layer | `system-status.link.{bt, adapter, ecu}` state + `available` + `ts` | **S109 US-876-*** | Atlas / Ralph |
| Capture per feed | `capture-health.feeds` | exists (US-688); **`state: faulted` + `reason` in S113** (Atlas B1) | Atlas / Ralph |
| Sync | `system-status.sync {lastOkTs, rowsWaiting, edrRowsWaiting, notCounted}` | **S109 US-916** | Atlas / Ralph |
| WiFi | `system-status.wifi {state, ssid, rssiDbm, home, ts}` + `source.wifi {available, reason}` | **S109 US-732** | Atlas / Ralph |
| UPS cell | `states/battery-health` (`vcellV`, `soc`, health verdict + reasons + margin, `ts`) | exists | — |
| Parked (every parked-only control) | `states/gear` `{available, gear, reason}`; parked = `"P"` or `"N"` and available, through the US-511 8 s / 3 s debounce (§4.7.2) | exists (US-687-a/b); **the debounce's input moves from `idle` to gear: US-511 reopened (b0)** | Ralph |
| Power source | `system-status.power.source` (`external` \| `battery`) | exists (US-668) | — |
| Pi health | `system-status.pi {cpuTempC, throttled, throttledHex, throttledSinceBoot, diskFreeBytes, diskThresholdBytes, diskVerdict, uptimeS, overLimit[], ts}` | **S109 US-877-a** | Atlas / Ralph |
| Version | `.deploy-version` via the `#version-chip` reader | exists (Atlas P8) | — |
| Settings | `/settings` overlay (`OVERRIDABLE_KEYS`), re-read on write | exists; **brightness key(s) new, US-878-c**; **`autoDim.luxMin` / `luxFull` join `OVERRIDABLE_KEYS`** with the cross-key rule `luxFull > luxMin` on effective values (POST 400) | Atlas |
| Issue counting | the verdict | **provider-derived** (Atlas 08-20 rule) | Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. **ARCH-061 fixtures** (`arch061-during-attempt`: BT + adapter up, ECU connecting or down):
   - chain `g g n`;
   - the sentence is `ECU not answering (key off?)`;
   - the verdict is **not** incremented;
   - the top bar shows the 3 dots;
   - **no element reads "Bluetooth down"**.
3. **Connecting fixture:** BT step neutral, `Bluetooth trying to link (key off?)`, verdict **not** incremented. No element anywhere reads `takes ~1 min`. **Retrying fixture:** BT step amber, verdict incremented, sentence = the `bt` member's `reason` verbatim.
4. **ARCH-062:**
   - A `null` layer renders a **dashed** step (and a hollow top-bar dot), never the solid `down` look.
5. **WiFi:**
   - `null` with no reason or `nmcli_absent` renders `--`, uncounted, never `down`;
   - `read_failed` renders `? not read` amber and counted;
   - `down` (not associated) renders `down` with the slashed glyph, from `state` alone. The string `not_associated` appears nowhere in the page or its tests;
   - associated with `rssiDbm` null renders the `home` word + `<ssid> · no signal level`, never `--`, never `down`, glyph unslashed;
   - `weak` is never amber, on the row or the glyph.
6. **UPS:**
   - never renders a runtime, `charging`, `crate`, SOC on the row, `car` or `wall`;
   - `on battery` is not amber;
   - no `min to cutoff` anywhere on the page or its details;
   - each `reasons.source` renders its §4.6.1 words; no element says `no UPS fitted`.
7. **🔴 The amber set equals the member set:** every amber element maps to exactly one `verdict.members[].key`, and every member has one (US-759). Assert it on every fixture.
8. **While not parked** (§4.7.2: a numbered gear, the 8 s hold, or the gear unknown; test a driving fixture, a hold fixture and a `link_down` fixture):
   - row taps open nothing;
   - SETTINGS › and ⋮ open the Settings band locked;
   - no control writes;
   - `🔒 view only — stop to change` with a numbered gear or in the hold; `🔒 view only — gear unknown` with the gear unavailable; no element on the page says `moving` or `engine off to change`.
   - **Parked-in-N unlocks:** `gear` `"N"`, `available` true, held 8 s ⇒ the band unlocks with the engine running. A 7 s hold does not.
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
14a. **DATA (Atlas A4 VC):**
   - top-level `never_written`, no stalled feed, ECU up ⇒ `no rows`, `no row logged this session`, 0 members, no ECU words;
   - UPS feed stalled, top-level `ok` ⇒ `stalled` amber, `UPS feed stalled.`, 1 member;
   - all feeds `ok` ⇒ `recording`, 0 members;
   - `stalled` appears on the row only when a `capture` member exists.
14b. **`sensor` member (S113):**
   - IMU `faulted` / `sensor_absent`, all else recording ⇒ `1 ISSUE`; value `recording` (never `stalled`); sentence `IMU sensor not found.` in amber; no `all 4 feeds writing`;
   - UPS read failed + LIGHT `sensor_absent` ⇒ `2 ISSUES`; two amber spans, `Light sensor not found. UPS gauge read failed.`, each with its own `data-member`;
   - UPS SOC `0xFFFF` ⇒ no member;
   - the feed recovers ⇒ the member clears and the sentence returns to `all 4 feeds writing`.
14. **Top bar:** the left cluster with the chain fits its 168.6 px side track, by `test_topbar_three_column_grid`'s measured model.
15. **LAST UPDATED (§4.6.3).**
    - Render harness: `UPDATED ›` sits left of `SETTINGS ›` on the verdict line in every state; ` ›` and the tap work only while parked.
    - The detail lists OBD, IMU, LIGHT, UPS, WIFI and SYNC in that order, each `<age> · <time>` or `--` when undated, with no state colour.
    - Grep: no `motion-updated` in the dashboard.
16. **Fit, in a real browser** (480 × 320 stage, shipped fonts): the verdict line doesn't wrap with `8 ISSUES`, and the LAST UPDATED detail body has `scrollHeight <= clientHeight`.

## 7. Fixtures (S10)
Each is a `system-status` (+ `capture-health`, + `battery-health` where named) payload, regenerated from the real builders (Atlas L7), never hand-typed.

| Fixture | Exercises |
|---|---|
| `arch061-during-attempt` | AC 2 (G1): key off, parked, home; BT + adapter up, ECU `connecting` (`g-g-n`) ⇒ `ECU not answering (key off?)`, `ALL OK` |
| `arch061-between-attempts` | AC 3 (G1): key off, parked, home; all three `connecting` (`n-n-n`) ⇒ `Bluetooth trying to link (key off?)`, every step neutral, `ALL OK` |
| `all-ok-driving` | all `up`, recording, home, external power |
| `bt-connecting` | AC 3, neutral, uncounted |
| `bt-retrying` | AC 3, `bt` member, `1 ISSUE`, reason verbatim |
| `adapter-silent` | `adapter` member, amber sentence |
| `link-not-read` | every layer `null`: dashed steps, hollow dots, `not read yet` |
| `capture-stalled` | `capture` member, value `stalled`, reason verbatim |
| `away-from-home` | `wifi.home false`, `away from home`, rows waiting, uncounted |
| `rows-not-counted` | `notCounted: ["<table>", "<table>"]` ⇒ `12,345+ rows waiting` on the row, the names in the detail, never folded into the count |
| `wifi-weak-home` | `home` green, `weak signal`, glyph neutral |
| `wifi-not-read` | `null`, `not_read` ⇒ `--`, `not read yet`, uncounted |
| `wifi-associated-no-level` | W1: `available: true`, `state: null`, `ssid` set, `rssiDbm` null ⇒ the `home` word, `<ssid> · no signal level`, glyph unslashed |
| `wifi-nmcli-absent` | dev box ⇒ `--`, `no WiFi tool on this host`, uncounted |
| `wifi-read-failed` | `wifi` member ⇒ `? not read` amber |
| `ups-on-battery` | `on battery` neutral, VCELL + age, no SOC on the row |
| `ups-gauge-unreadable` | typed NA |
| `ups-source-provider-absent` / `-unreadable` / `-read-failed` | W2: `power source unknown` on the row; the §4.6.1 words in the UPS detail |
| `pi-hot` | `pi` member, one limit, the Pi line |
| `pi-multi-limit` | `Over limit: CPU temp, throttling, disk.` |
| `ecu-retrying-after-keyoff` | I1/I2: BT + adapter up, ECU retrying ⇒ `ECU not answering (key off?)`, ECU step and dot `--text-secondary`, `ALL OK` |
| `adapter-down-bt-down` | I1/I2: `bt` member speaks; the adapter step isn't amber |
| `capture-stalled-ecu-silent` | A4: top-level `stalled`, ECU `down` ⇒ `stopped` in `--text-secondary`, `ECU not answering`, uncounted |
| `capture-never-written-ecu-up` | A4 VC 1 / W3: cold boot ⇒ `no rows`, `no row logged this session`, 0 members |
| `capture-ups-feed-stalled` | A4 VC 2: top-level `ok`, UPS feed stalled ⇒ `stalled` amber, `UPS feed stalled.`, 1 member |
| `sensor-imu-absent` | AC 14b: `sensor` member, `IMU sensor not found.`, value `recording` |
| `sensor-two-faults` | AC 14b: LIGHT `sensor_absent` + UPS read failed ⇒ `2 ISSUES`, two spans |
| `sync-days-old` | I3: `synced Oct 12`, never a bare time |
| `sync-stale-glyph` | I4: `sync.stale`, no member ⇒ sync glyph neutral |
| `wifi-down` | A6: `available: true`, not associated ⇒ `state: down`, reason null, `down`, slashed glyph (replaces `wifi-not-associated`) |
| `ups-fresh-12s` | I6: `on external power · 12 s ago` |
| `last-stop-ungraceful` | I7: LAST STOP line in the UPS detail, neutral |
| `two-issues` | `bt` + `pi`: `2 ISSUES`, the amber set equals the member set |
| `verdict-absent` | `--`, never `ALL OK` |
| `settings-write-rejected` | AC 9 |
| `settings-lux-cross-rejected` | AC 9: a crossing write gets a 400 ⇒ `couldn't save`, snap back |
| `settings-floor-from-minlevel` | AC 9: FIXED floor = effective `minLevel` (0.75 ⇒ 75 %); `minLevel` unreadable ⇒ FIXED disabled, `Unknown` |
| `settings-locked-hold` | AC 8: stopped, gear `N`, inside the 8 s hold ⇒ `stop to change` (replaces `settings-locked-idling`: an idling car at rest is now parked) |
| `settings-locked-gear-unknown` | AC 8: `states/gear` unavailable (`link_down`) ⇒ `gear unknown` |
| `settings-parked-idling` | AC 8: gear `N`, engine idling, held 8 s ⇒ unlocked |
| `settings-locked-driving` | AC 8, incl. one in-flight write |

**Retired:**
- `ups-low`. There's no UPS member (Spool + Atlas P5), so the fixture had no basis.
- `prev-session-ecu-stale` (S109 L5): every layer is this session only (ARCH-062), so a previous-session success can't be published.
- `wifi-not-associated` (Atlas A6): the reason never existed; `wifi-down` replaces it.

## 8. Out of scope
- detecting wall vs car power (US-729);
- battery runtime (capacity unmeasured);
- managing networks (Atlas WiFi ruling: display only);
- the audio alerts setting (US-538, deferred);
- the sync verdict member (US-917).

## 9. Open items
- **Atlas:**
  - ~~the brightness override key(s) and the apply tags for brightness and auto-dim (US-878-c)~~ **RULED 2026-10-19 (S110 B4, B12):** `overrideLevel`; `applies on reload` / `applies at the next light reading` (§4.7);
  - whether `restedHistory` is ever reader-facing (with Spool).
- **Build note (UIDEV-010):** shipped `healthValue` returns `—` for an unknown health. §4.4's rule is that `--` is the one no-data mark, so the UPS detail owes the swap when it is built.
- **CIO:**
  - whether the effective `minLevel` floor is right, in the car.
- **Marcus:** ARCH-061 + US-713 close through this design.

## 10. The OEM mockup (v2, 2026-10-22, UIDEV-010)
**`specs/v030-system-page-oem.html` v2 is brought up to this spec. Build from it, System and Settings both.** It is rebuilt on the §5 provider shapes (verdict members, per-layer link with `null`, the WiFi reason, sync with `notCounted`, battery-health + `power.source`, the Pi block), and it draws every §7 fixture: 41 panels, including the detail and Settings views.
- **AC 7 is asserted, not eyeballed:** every amber element carries the member it belongs to (`data-m`), and on every fixture the amber set equals `verdict.members` (41/41 in the mockup's harness).
- **Corrections it made to this spec:** the yesterday sync stamp (§4.3), the two apply tags (§4.7, Atlas B12), and the tag wrap and description length (§4.7).
- **Unchanged and not drawn:** the ⋮ overlay's service band (US-659's rules).
- **UIDEV-011 (2026-10-22): parked is the gear fact (§4.7.2).** The car control is now Parked (`P`/`N` held 8 s) · the hold · Driving · Gear unknown, and the lock line is `stop to change` or `gear unknown`. `settings-locked-idling` is replaced by `settings-locked-hold`, plus `settings-locked-gear-unknown` and `settings-parked-idling`: 43 fixtures.

### Superseded: the gaps the older mockups had
The 2026-10-12 System mockup, the 2026-10-15 OEM mockup (`proposals/`, never in the repo) and the 2026-10-13 Settings mockup all predate the S110 fold. Their gaps were these, and the v2 mockup closes every one:
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

Brought up on UIDEV-010 (2026-10-22).
