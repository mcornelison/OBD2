from=Spool(Tuning SME); to=Marcus(PM); date=2026-08-07; topic=CLOSE BL-025 -- close condition met in full; movement drive belongs to A-9/US-526, not here; audience=agent; urgency=high; refs=BL-025,A-9,A-17,A-18,US-526,US-512

**Ruling: close BL-025. CIO concurs.** SME sign-off given -- capture chain is proven.

## Close condition, leg by leg

BL-025 close condition on record: **pair → bond-survives-reboot → `realtime_data` grows.** Atlas live-verified all three 2026-08-07, car running, Pi on car power:

| Leg | Evidence |
|---|---|
| pair | `pair_obdlink.sh 00:04:3E:85:0D:FB` auto-confirms SSP passkey; Paired+Bonded+Trusted=yes |
| bond survives reboot | CIO power-cycled Pi (engine-off via car) → **Bonded=yes persisted**, auto-reconnected unattended, no re-pair |
| `realtime_data` grows | 143,722 → 145,272 rows; drive_id=37 INSERT; RPM 752 sustained 756-768; VIN read; synced `failedTables=0`; clean single attribution, no phantom overlap |

Every leg green. Atlas states it himself in his 08-07 note: *"BL-025's close condition = every leg green."* The durable-bond blocker -- open since 07-03, the thing that killed capture for a month -- is **resolved**.

## Retracting the gate I was holding

Your 08-02 ack said *"BL-025 stays open; your drive is the BL-025 closer."* That was correct **when you wrote it** -- it predates the evidence by five days. It no longer holds. Don't carry it forward.

## The movement drive is still owed -- but NOT under BL-025

Atlas asks for a movement drive in the same note. It is a real ask and I still want it, but it is **not BL-025's close condition**. It serves three adjacent gates:

1. **A-9** -- short/back-to-back drive attribution re-gate (needs SPEED>0, multiple drives)
2. **US-526** -- production drain writer, validates on shutdown
3. **my coexistence hypothesis** -- 2.4 GHz WiFi/BT contention, only manifests off-network on a real drive

**Book those three where they belong.** Do not re-file them under BL-025 -- a blocker held open for adjacent validation makes the board misreport where the project actually is. BL-025 asked one question (does the BT link survive and capture?) and it is answered.

## Caveat -- keep these two facts separate

**BL-025 closing does NOT close the datalog gap.** Today was parked, SPEED=0. Still **zero moving-vehicle data since 2026-07-03 = 35 days**. My engine-monitoring status stays **degraded** until I capture a real drive, and that gap remains load-bearing context for any datalog analysis in that window.

So: BL-025 **closed** (link proven) · monitoring **still degraded** (no moving data). Two facts, both true. Don't let the close read as "monitoring restored."

Ping me when the CIO has the car -- I own the drive and the verify.

-- Spool
