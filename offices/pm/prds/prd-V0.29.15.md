---
sprint: 61
version: V0.29.15
status: draft
createdAt: 2026-07-19
createdBy: Marcus (PM)
selectedStories: [US-475, US-476]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS
feature: F-120 (OBDLink LX / Bluetooth connectivity reliability)
theme: Make the OBDLink LX dongle re-pairable and self-recovering (Atlas R2a/R2b) so capture survives BT drops + factory resets
atlasReview: "SOUND 2026-07-20 (inbox 2026-07-20-from-atlas-prd-review...). US-475/476 correctly scoped (both read MAC from config -> pick up correct ...3E...). Design-fork ANSWER: on-demand (do NOT scope discovery-redesign now -- MAC is stable/burned-in). SEQUENCING FLAG: F-120 is all Bluetooth-reliability -> the wired/USB-adapter decision should be made BEFORE investing here (a wired adapter eliminates the whole BT failure class)."
---

# PRD: V0.29.15 -- OBDLink LX / Bluetooth connectivity reliability (F-120)

| Field | Value |
|---|---|
| Version | V0.29.15 (patch on `dev`, forks after V0.29.14) |
| Theme | The 2026-07-17/18 session had the LX go catatonic twice + revealed the only re-pair path is dead. Restore re-pairing + add real auto-recovery so a BT drop / dead-SPP state doesn't mean permanent capture loss. |
| Status | DRAFT (pending Atlas review). |
| Lane | Pi BT/dongle layer; **dongle/Pi bench-validated** (needs the LX + Pi, not a drive). |
| Stories | US-475, US-476 under **F-120** (new, E-OPS) |
| Deploy + validate | Deploys from `dev`; validated on the bench Pi + live dongle. |

## Why now (Atlas R2, 2026-07-19 routing)

The dongle went catatonic twice in the live session, and two gaps make that unrecoverable in the field:
- `scripts/pair_obdlink.sh` is **dead on the Pi's Trixie bluez** — its pexpect waits for the old `[bluetooth]#` prompt; new bluetoothctl is `[bluetoothctl]>` → timeout, can't re-pair. It's the *only* re-pair path.
- The reconnect loop only **rfcomm-rebinds**; when the LX drops into its dead-SPP/BT state it needs a full BT disconnect + re-page, else it loops forever on a stale binding.

**Sequencing note (PM):** these are rated MED (below R1/F-107), but they materially improve the odds of a clean **drive-35** capture re-gate — a dropped dongle mid-drive with no auto-recovery could waste the drive. If the CIO wants belt-and-suspenders before the big validation drive, this sprint can be pulled ahead of V0.29.14's deploy. Recommendation left to the CIO; default order is after V0.29.14.

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Summary |
|---|---|---|---|
| **US-475** | issue | S | **R2a** — fix `pair_obdlink.sh` for Trixie bluez (`[bluetoothctl]>` prompt; tolerate legacy `[bluetooth]#`); lift the working handling from the Pi's `~/atlas_pair.py`; read MAC from config (pairs with US-477). Restores the only re-pair path. |
| **US-476** | issue | M | **R2b** — real auto-recovery: after N consecutive read failures do a full BT disconnect + re-page (`bluetoothctl connect`), not just an rfcomm rebind; bounded/backed-off; log once per episode; graceful when the dongle is simply absent. |

## Design fork — ANSWERED (Atlas 2026-07-20): on-demand

US-476 stays scoped to the **N-failure → re-page** slice. Atlas: **do NOT scope the discovery-redesign now** — the "MAC changes on factory reset" premise was part of his phantom-device error; a BT MAC is **burned-in and stable** (`00:04:3E:85:0D:FB`, CIO's paired phone). A config-sourced fixed MAC is fine; only escalate to a discovery redesign if US-476 genuinely can't recover without re-discovery (its conditionalOutcome already routes that to Atlas).

## ⚠️ Decide BEFORE building this sprint: wired vs Bluetooth (Atlas flag)

F-120 is **entirely Bluetooth-reliability** work. The standing recommendation (CIO's + Atlas's) is a **wired/USB OBD adapter** to eliminate the whole BT failure class. **If the CIO goes wired, most of V0.29.15 is wasted.** So the wired-vs-BT decision should be made before investing in F-120 — surfaced to the CIO as an open decision.

## Notes / sequencing
- Rule-13 retired → Atlas's PRD review IS the gate.
- US-477 (R2c, the repo-MAC landmine) is the same F-120 feature but ships in **V0.29.13** (pure config, no dongle) — fast-tracked ahead of these two.
- On Atlas PASS: generate `sprint.json` → `sprint_lint` → branch `sprint/sprint61-V0.29.15` → CIO runs `ralph.sh`.
