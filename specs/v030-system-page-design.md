# V0.30 System page (+ detail screens + Settings) — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-12 · **Status:** CIO-APPROVED design (brainstorm 2026-10-12), awaiting V0.30 DoD + grooming
**Mockup:** `proposals/2026-10-12-v030-system-page.html` → https://claude.ai/artifact/47FkWPp39fVQL3ciKph8ra (**layout A is the locked one**)
**DoD lines served:** 7 (themed pages: System + power), 8, 12 (closes ARCH-061 and US-713; carries US-729, US-732, US-742, US-759 as rules)
**Also:** F-126 Settings, **brought INTO V0.30 by the CIO 2026-10-12** (reverses R16 for F-126).
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose (CIO)
**"Is everything OK?"** A verdict first, then one row per subsystem with a state and a plain sentence. Diagnostics live one tap away (parked).

## 2. Decisions locked (CIO, 2026-10-12)

| # | Decision | CIO choice |
|---|---|---|
| S-1 | Structure | **One summary page + detail screens** |
| S-2 | Purpose | "Is everything OK?" |
| S-3 | UPS level | **Voltage first, SOC as `≈`**; never a runtime |
| S-4 | OBD link | **3-step chain** BT → ADAPTER → ECU; compact 3-dot version in the top bar |
| S-5 | Rows | **OBD link · capture + sync · WiFi · UPS** |
| S-6 | Pi health | **Detail only**, opened from the verdict line |
| S-7 | Settings access | **Both**: SETTINGS button on System (parked) **and** the ⋮ overlay |
| S-8 | WiFi | **Green home · yellow other network · grey down · `?` not read** |
| S-9 | Layout | **A · Verdict and rows** |
| S-10 | ECU silent with BT + adapter up | **Not an issue**: grey step + `ECU not answering (key off?)` |
| S-11 | Settings contents | Brightness override + auto-dim ends · auto-rotate · calibration + auto-analyze · power mode |

**Why three layers and not "powered / BT / ECU" (ARCH-061's wording):** the Pi cannot measure "dongle powered"; an unpowered dongle and an out-of-range one look identical. It **can** measure Bluetooth `Connected`, the ELM adapter answering AT commands (works key-off), and the ECU answering. Those three are the honest layers.

## 3. Layout (480 × 320; body 258; ≈ 232 used)

```
┌──────────────────────────────────────────────┐ top bar: ●━●━○ WIFI SYNC ⚠ (chain as 3 dots)
│ ALL OK                           SETTINGS ›  │ ~40  verdict --fs-primary; button parked only
├──────────────────────────────────────────────┤
│ OBD    [BT]━[ADAPTER]━[ECU]                   │ ~48
│        ECU not answering (key off?)          │
├──────────────────────────────────────────────┤
│ DATA   idle · synced 6:42 PM                 │ ~48
│        not driving · 0 rows waiting          │
├──────────────────────────────────────────────┤
│ WIFI   home                                  │ ~48
│        DeathstarWifi · strong                │
├──────────────────────────────────────────────┤
│ UPS    4.12 V                                │ ~48
│        ≈ 92 % · on car power                 │
└──────────────────────────────────────────────┘
```

- Row label `--fs-label` `--font-display`; value `--fs-label` mono in its state colour; sentence `--fs-meta`.
- These rows are **read parked or glanced for colour**. The verdict is the driver-glance element (`--fs-primary`).
- Every row ≥ 44 px tall (touch target when parked). Long text **ellipsizes on one line**; the full text is in the row's detail (no silent clip: the ellipsis is the visible sign).

## 4. Behaviour

### 4.1 Verdict
- `ALL OK` (`--green-ok`) or `n ISSUE(S)` (`--amber-warn`). **The count names its members** (carries US-759): the counted rows show amber, and nothing else does.
- **Counted as issues:** BT not linked · adapter not answering while BT is linked · capture stalled while the ECU answers · sync failing **at home** · WiFi `not read` · UPS below the provider's low band · any Pi-health limit.
- **Not issues:** ECU silent (S-10) · away from home (sync waiting is expected) · WiFi down away from home.
- Tap the verdict (parked) ⇒ **Pi health** detail.

### 4.2 OBD chain
| Step state | Look |
|---|---|
| working | `--green-ok` outlined step |
| connecting / retrying | `--amber-warn` (**closes US-713**: "connecting" is visible) |
| not answering | `--text-tertiary` |

Sentence = the **first** layer not answering + likely cause: `Bluetooth not linked` · `Bluetooth connecting… (takes ~1 min)` · `adapter not answering` · `ECU not answering (key off?)` · `ECU answering`.
**Top bar, every page:** the same chain as three dots joined by short lines, **replacing the single BT glyph**. **Closes ARCH-061**: one icon covering three facts never returns.
⚠ **ARCH-062 rule carried:** a layer's state comes from **this session's** reading; a previous session's success must never render as current (`available` + `ts` per layer).

### 4.3 DATA (capture + sync)
- Value: `recording` / `idle` / `waiting` + `synced h:mm AM` (local 12-h, US-559 helper).
- Sentence: `all 4 feeds writing` (R3: OBD, light, IMU, UPS) or names the silent feed · `n rows waiting`.
- Away from home: `away from home`, neutral, not an issue (F-155 at-home sync).

### 4.4 WIFI (carries US-732 + US-742)
`home` green · `other network` amber-yellow · `down` grey · `? not read` amber and **counted**. Atlas 2026-08-20: unknown is never `down`. The **emitter** derives `state`; the page applies no RSSI threshold. SSID + strength word in the sentence.

### 4.5 UPS
- Value: `4.12 V` (VCELL, trusted). Sentence: `≈ 92 %` (modelled SOC, marked) `· on car power` / `· on battery`.
- **Never a runtime** (pack capacity unmeasured). **Never** `charging` / `crate` (registers absent on this silicon; shared MEMORY).
- **No wall-vs-car row** (carries US-729): the source word is only what the power state already reports, not a detected "wall".

### 4.6 Detail screens (parked; Back returns to System)
| Detail | Contents |
|---|---|
| **OBD** | per layer: state, since when, last success `ts`, retry count; adapter MAC; the plain sentence |
| **DATA** | per feed (OBD, light, IMU, UPS): writing / silent + last row age; sync: last confirmed delivery, rows waiting, at-home state |
| **WIFI** | SSID, strength (word + dBm), IP, home-network yes/no |
| **UPS** | VCELL, ≈SOC + caveat, source, **pack epoch** (`4×18650 since 2026-09-26`), short voltage trend |
| **Pi** (from verdict) | CPU temperature, disk free, uptime, version; any limit crossed named in amber |

### 4.7 Settings (F-126, now in V0.30)
Reached from **SETTINGS ›** (System, parked) and from the **⋮** overlay band. **Parked only.**

| Setting | Control | Note |
|---|---|---|
| Brightness | `AUTO` / `FIXED nn %` | Light page shows the override (amber) |
| Auto-dim ends | two lux steppers (dim-start, full-bright) | also the DAY/DUSK/NIGHT boundaries (Light page) |
| Auto-rotate pages | off / seconds | existing `autoRotateS`, 0 = off (US-541-a) |
| Calibration | toggle | existing |
| Auto-analyze | toggle | existing |
| Power mode | car / wall | existing; CIO kept it (S-11) |

**Visual design (CIO-approved 2026-10-13; mockup https://claude.ai/artifact/Vfsd6VugUGfoQAMYJZPo6R, `proposals/2026-10-13-v030-settings-screen.html`):**
- Top bar: `‹ BACK` (left) · clock · `SETTINGS` (page-name slot). Two sections, **DISPLAY** (brightness, auto-dim range, rotate pages) and **SYSTEM** (calibration mode, analyze each drive, power source), with headers in `--accent`.
- Each row: name (Michroma), a one-line plain description, the control on the right, then a status line (`stored: …` / `saving…` / `saved · …` / `couldn't save · kept …`) and the apply tag (`applies now` / `next drive` / `after a restart`).
- **Controls (CIO):** **steppers `− value +`** for numbers (40 px targets): brightness 5 % steps (20–100 %, shown only when FIXED); auto-dim on a 1-2-3-5 lux ladder whose two ends **cannot cross**; rotate pages `OFF · 5 · 8 · 10 · 15 · 30 s`. Segmented choices for `AUTO|FIXED` and `CAR|WALL|UNKNOWN` (power mode stays **3-state**, as shipped; `UNKNOWN` = let the system decide). Switches for the two booleans.
- **Each change saves on its own** (CIO); no Save button.
- The Light page shortcut opens Settings **scrolled to Brightness**.
- A footer line points to the ⋮ menu for service controls; they never appear in Settings.

One list; **scrolls with a visible scrollbar** if taller than the panel (no silent clip). **Honest write, unchanged from W-18:** each control shows the real stored value; on tap `saving…` → confirm **from the re-read**, or snap back + `couldn't save`; never optimistic success. Per-row apply tag (live / next drive / restart). Destructive service controls stay in their own band below, with confirms (unchanged).

## 5. Data contract

| Need | Source | Status | Owner |
|---|---|---|---|
| BT linked | bluetoothctl / rfcomm | exists (ARCH-061 measurement) | publish per layer |
| **Adapter answering** | ELM AT response | **not published separately** | **Atlas** |
| ECU answering | OBD session | exists | — |
| Per-layer `available` + `ts` (this session) | — | **ARCH-062 shape fix** | Atlas |
| Capture + per-feed status | capture-health | exists in part; **per-feed** needed | Atlas |
| Sync | sync state (F-155) | exists | — |
| **WiFi** | contract approved 2026-08-20 | **never wired (US-732)** | **Atlas/Ralph** |
| UPS | VCELL, SOC, source | exist | — |
| **Pi health** | CPU temp, disk, uptime | **new provider** | Atlas |
| **Settings keys** | brightness override, auto-dim ends | **new** | Atlas |
| Issue counting | which states count | **provider-derived verdict** (Atlas 08-20 rule) | Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. ARCH-061 fixture (BT + adapter up, ECU silent): chain `g g n`, sentence names the ECU, verdict **not** incremented, top bar shows the 3 dots, and **no element reads "Bluetooth down"**.
3. Connecting fixture: BT step amber, sentence says connecting.
4. ARCH-062 fixture: a previous-session ECU success with this session silent renders grey, never green.
5. WiFi `null` + `available:false` renders `? not read` (counted), never `down`.
6. UPS never renders a runtime, `charging` or `crate`.
7. The verdict count equals the number of amber rows/details; each counted item is visibly marked (US-759).
8. SETTINGS button and row taps absent while moving.
9. Settings: a rejected write snaps back with `couldn't save`; the success state shows the re-read value.
10. Long row text ellipsizes on one line (no wrap overflow, no clip).
11. No literal colour or px in this page's CSS.
12. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`arch061-key-off-home` · `all-ok-driving` · `bt-connecting` · `adapter-silent` · `away-from-home` · `wifi-not-read` · `ups-low` · `pi-hot` · `prev-session-ecu-stale` · `settings-write-rejected`.

## 8. Out of scope
Detecting wall vs car power (US-729) · battery runtime (capacity unmeasured) · managing networks (Atlas WiFi ruling: display only) · audio alerts setting (US-538, deferred).

## 9. Open items
- **Atlas:** adapter layer; per-layer this-session state (ARCH-062); per-feed capture; WiFi wiring; Pi-health provider; provider-derived verdict; new settings keys.
- **Marcus:** F-126 IN (already sent); ARCH-061 + US-713 close through this design.
