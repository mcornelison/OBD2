---
sprint: 60
version: V0.29.14
status: draft
createdAt: 2026-07-15
updatedAt: 2026-07-20
createdBy: Marcus (PM)
selectedStories: [US-474, US-477, US-479]
priority: HIGHEST -- the true-gate sprint (reliable + provable OBD capture)
shippedNotInSprint: [US-386, US-387, US-388, US-389, US-390]  # F-107 SHIPPED Sprint 47/V0.29.1
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS
feature: F-117 (OBD-capture reliability) + F-120 (US-477 OBD MAC integrity)
theme: Restore + PROVE reliable OBD Bluetooth capture -- harden the A-17 fix, self-heal the phantom-MAC drift, and give the CIO a pre-drive green light
atlasReview: "US-474 PASS-w/-corrections 2026-07-20. US-477 (re-expanded) + US-479 (new) routed 2026-07-20 for design-gate. Freeze retired."
---

# PRD: V0.29.14 -- Restore + prove reliable OBD Bluetooth capture (THE true-gate sprint)

| Field | Value |
|---|---|
| Version | V0.29.14 (patch on `dev`) |
| Priority | **HIGHEST** — this is the gate the CIO named: a validated Pi that connects over BT and *captures*, provable before a drive |
| Theme | Make OBD capture reliable **and self-verifying** so a weekend of drives never again captures zero rows |
| Status | DRAFT — US-474 Atlas-cleared; US-477/US-479 routed for review |
| Lane | Pi OBD-capture path + deploy config; **load-bearing** |
| Stories | US-474, US-477, US-479 under **F-117** / **F-120** |
| Deploy + validate | Deploys from `dev`; end-to-end proof = the combined IRL drive-35 re-gate (A-9/A-17/A-16-Bug3/BL-016) |

## Context — the archaeology (2026-07-20)

The CIO drove all weekend and captured **nothing**. Root-caused (git + code + the CIO's paired-phone photo):

- **Ground truth (unchanged, valid):** dongle `OBDLink LX` @ `00:04:3E:85:0D:FB`, SSP passkey auto-confirm (**not** PIN 1234), `/dev/rfcomm0` ch1, bond persists since Session 23. **No architect change ever touched the BT link** (connect/rfcomm/pairing byte-identical across US-441/A-17/US-432; a raw read got 6/6 live RPM on the same MAC while the service failed).
- **Two breaks, one hallucinated + one real:**
  1. **Hallucinated (the connection break):** on 2026-07-17 the architect repointed the Pi's live `/etc/default/obdlink` + `.env` to a **phantom MAC `00:04:3C:84:15:6B`** (mis-ID'd stranger's device). If still on the Pi, rfcomm binds a nonexistent device → no connection. **Fixed by the ops action-item AI-004** (revert Pi config; likely 2-min fix) — this sprint's **US-477** makes the deploy self-heal it.
  2. **Real (the capture race):** US-441 (`ed5ec77`, V0.29.8, 2026-07-03) serialized the realtime logger under `_ioLock` but left DTC reads on the raw unlocked path → connect-edge race → 0 rows even when connected. A-17 (`4a17bc1`) fixed it (on `dev`+deployed, unvalidated on car); **US-474** hardens it.
- **Last-known-good:** Drive 27 (2026-06-06, V0.28.0, 4,771 rows, `data_quality=full`); last capture Drive 34 (2026-07-03).

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Summary |
|---|---|---|---|
| **US-474** | issue | S | **A-17 capture-fix hardening.** Drop the raw `getattr` fallback (`dtc_client.py:353-354`) so DTC reads always serialize; add `query()` as a typed `ObdConnectionLike` Protocol member (`:137`); add a **non-mocked connect-edge concurrency regression** (logger + KOEO DTC read on one connection, no interleave — the GAP-1 F-117 missed); full pi suite + mypy green. |
| **US-477** | issue | S | **OBD MAC integrity.** Guard test pins repo MAC to `00:04:3E:85:0D:FB` / name `OBDLink LX` (RED on the phantom `…3C…`); **deploy re-asserts the canonical MAC into the Pi's `/etc/default/obdlink`** every deploy so a drifted Pi (the 07-17 phantom) self-heals instead of binding a dead device. |
| **US-479** | issue | M | **Pre-drive connect+capture green-light.** One CIO-runnable command (compose `verify_bt_pair.sh` + `verify_live_idle.sh`) that proves BT link → rfcomm bind → `realtime_data` rows landing, **exercising the connect-edge (KOEO DTC + logger)** so it can't happy-path-pass while the race kills capture. KOEO + live-idle modes; bench mode for Ralph. So the CIO never drives blind again. |

## Sequencing
1. **AI-004 (CIO ops, NOW):** revert the Pi's MAC to `…3E…` → likely restores the connection immediately (independent of this sprint).
2. **Ralph sprint:** US-474 first (the fix), then US-479 (deps US-474), US-477 in parallel.
3. **IRL drive-35 re-gate** (CIO + Atlas): the combined A-9/A-17/A-16-Bug3/BL-016 proof. US-479 is the pre-drive green light that de-risks it.

## Not in this sprint
- **F-120 BT-reliability (US-475/476) — SHELVED** (CIO 2026-07-20: BT works fine; those were hallucinated; bond persists so re-pair rarely needed). See `prd-V0.29.15.md` (shelved).
- F-107 (US-386→390) — already shipped Sprint 47/V0.29.1.
