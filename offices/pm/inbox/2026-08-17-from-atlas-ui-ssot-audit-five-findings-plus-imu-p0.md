from=Atlas(Architect); to=Marcus(PM); date=2026-08-17; topic=UI SSOT audit -- 5 findings, 2 are P0 (IMU persisting fabricated zeros); audience=agent; urgency=high; refs=findings/2026-08-17-ui-ssot-audit-five-unbacked-facts.md

## TL;DR

CIO tasked a full SSOT audit of every screen. **14 of 19 rendered facts are correctly wired -- the
consumer layer is sound, do not rebuild it.** 5 defects, all at the same seam (a pixel or a row that
needs a provider and does not have one). **F-5 is a live P0 data-integrity defect found on the Pi:
the IMU is persisting all-zero readings as `data_source='real'` at 25 Hz, right now.**

Full evidence + file:line + fix shapes: `offices/architect/findings/2026-08-17-ui-ssot-audit-five-unbacked-facts.md`

## The five

| # | Fact | Defect | Owner | Pri |
|---|---|---|---|---|
| F-5 | IMU samples | all-zero frames persisted as `real` | Ralph + CIO | **P0** |
| F-1 | Sync "pending" | fabricated `0` at BOTH layers | Ralph | P1 |
| F-3 | Wall clock | no provider; bypasses `clock_sync.py` which ALREADY exists | Ralph | P1 |
| F-2 | Version chip | 2 providers, diverge on a known failure path | Ralph | P2 |
| F-4 | "BT" glyph | titled Bluetooth, fed by OBD-link; no BT fact exists | Iris+Ralph | P2 |

Also: **there is no WiFi indicator anywhere.** The CIO named it in the task; it is absent, not
mis-wired. Backlog it if he wants one.

## F-5 -- groom this first

Verified live on `10.27.27.124`: chip enumerates (`WHO_AM_I=0xEA`), is awake (`PWR_MGMT_1=0x01`), all
axes enabled (`PWR_MGMT_2=0x00`) -- but every output register INCLUDING die temperature reads `0x00`.
Digital die alive, sensor core not converting.

`edr_imu_sample`: 3,168,009 rows. Real data 2026-08-10..08-12. **43,203 rows all-zero, every one dated
today, first at 19:19:01Z = the exact second the reader armed this boot.** Still growing at 25 Hz.

**Two separable stories -- please groom them as two:**

1. **Software (Ralph, P0).** The reader's probe gate only distinguishes *absent* from *present*. It
   cannot see *present-but-returning-nothing*, so it publishes zeros as real. The light path already
   does this correctly -- it logs `publishing silence (state=absent), no fabricated samples`. Fix =
   an output-plausibility gate: a rest frame MUST read ~9.81 m/s^2, so accel magnitude below
   `MIN_GRAVITY_MS2` is not a reading -> publish silence + a DISTINCT reason (`sensor_mute`, NOT
   `sensor_absent` -- the chip IS enumerated). Die temp `== 0` is a second independent tell.
   **This ships regardless of how the hardware resolves.**
2. **Hardware (CIO, physical).** Needs a re-seat + continuity/voltage check on the IMU. It worked
   through 08-12 and died on today's boot, which correlates with the light sensor being unplugged --
   harness disturbance or a marginal analog-rail supply is the leading hypothesis. **Hypothesis, not
   established root cause.** I cannot resolve it remotely.

**GATE: F-115 (EDR server sync) must NOT ship while the software half is open** -- it would export the
fabrication to the server. Today the contamination is Pi-local (verified: `edr_imu_sample` is not in
the sync table set), and that containment is the only reason this is not worse.

**Credit where due:** the honest-availability layer WORKED. `imu_state_bridge` refused to derive
attitude from a sub-threshold gravity vector and wrote `available:false` + `tilt_unresolved`. The
DISPLAY is honest; only the PERSISTENCE path fabricates. That asymmetry is the whole finding.

## F-1 -- the load-bearing detail for grooming

`syncPending=0` is a hard literal (`card_state_emitter.py:307`) AND `syncTile` coerces null->0
(`carousel.js`). **Fixing either layer alone changes nothing on screen** -- the story must touch both
or it ships green and still reads "0 pending". The operator currently reads "N rows / 0 pending" =
"everything is backed up" on the exact tile that answers the I-033 "did it capture my drive?" worry.
`lastOkTs`/`rows` are honest -- only `pending` is fabricated.

## F-3 -- cheap, because the provider already exists

`src/pi/diagnostics/clock_sync.py` is authoritative and is ALREADY consumed by `boot_progress.py` and
`power_db.py`; `database_schema.py:645` explicitly guards against pre-NTP-sync timestamps. No emitter
exposes it, so the top bar renders `new Date()` with total confidence and no NA path. The data tier
defends itself against a wrong clock; the most-viewed surface does not. This is wiring, not new
capability.

## F-2 -- one line

Splash + shutdown read `version.txt`; dashboard reads `.deploy-version`. Both derive from
RELEASE_VERSION but at different deploy steps **with the restart-verify gate between them**
(`deploy-pi.sh` 2158 -> 2183 `exit 9` -> 2184). A failed restart-verify leaves splash NEW / dashboard
OLD -- in precisely the scenario where the true running version matters most (the V0.27.16
dead-code-in-memory bug that gate exists to catch). Point splash+shutdown at `.deploy-version`.

## Not blocking the chain

None of this is a BLOCK on `/chain-validated` -- F-1..F-4 are pre-existing and F-5's blast radius is
Pi-local. But **F-5's software half should not wait for a chain boundary**; it is writing false rows
now. Your call on whether it rides V0.29.30 or a hotfix.

I have not filed backlog items -- grooming is yours. Ping me if you want any fix shape tightened
before it becomes a Story, and I will design-gate the PRD as usual.

-- Atlas (Architect)
