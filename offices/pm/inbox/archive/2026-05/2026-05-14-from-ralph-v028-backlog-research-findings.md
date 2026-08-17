# V0.28+ backlog candidates from CIO-directed research + V0.27.10 deploy-ready handoff
**From:** Ralph (Rex)
**To:** Marcus (PM)
**Date:** 2026-05-14
**Priority:** routine (backlog grooming) + deploy-routing
**Re:** Citation Links research task + Sprint 36 ship

---

## V0.27.10 is committed + pushed -- ready for `/sprint-deploy-pm`

Sprint 36 / V0.27.10 final state on branch `sprint/sprint36-bugfixes-V0.27.10`:

- **Commit:** `6184a7f feat(sprint-36): V0.27.10 Bug Fixes -- 4 stories US-338/339/340/340b`
- **Files:** 10 (5 src + 5 tests). +965/-12 lines. All test additions; one existing US-211 integration test assertion updated to match the US-340b dedup contract (called out inline).
- **Verification ledger:** 285 passed cumulative no-regression run; lint clean; red-green-revert-green TDD verified per fix.
- **Stories:**
  - US-338 / I-033: BT no-reconnect after engine cycle -- `_handleReconnectionFailure` now spawns a daemon `runReconnectHeartbeat` (US-301/V0.27.1/US-325 machinery, exponential backoff up to 15-min ceiling) instead of giving up silently
  - US-339 / I-034: SQLite "disk I/O error" -- `contextlib.closing` around `sqlite3.connect()` in `pushDelta` + `pushDriveCounter`; eliminates the ~13-fd-per-sweep leak
  - US-340 / I-035: drive-time HTTP retry waste -- `SyncClient.hasRouteToServer()` + orchestrator gate skips `pushAllDeltas` when no route; eliminates ~84s of doomed TCP SYNs per ACTIVE-mode cadence tick
  - US-340b (CIO mid-sprint add): connection_log state-change-only dedup -- ~99% row-volume reduction during sustained outages (was ~2000 rows/day)

**IRL validation gates** (CIO post-deploy):
- US-338: 2-leg pharmacy pattern -> drives 13+14 both materialize with >100 rows + correct `drive_id`
- US-339: 6h+ bench soak -> zero `disk I/O error` lines; fd count for `eclipse-obd` PID stays flat (~5-10) instead of climbing
- US-340: 10-min drive -> server-side `connection_log` + `sync_history` row counts during the drive should be near-zero
- US-340b: post-deploy bench soak -> `connection_log` row volume during a sustained adapter outage should be ~5-10 rows total, not 2000

You can `/sprint-deploy-pm` whenever you're ready.

---

## V0.28+ backlog candidates (from CIO-directed deep-dive into 4 reference repos)

CIO asked me to research the four GitHub repos in `specs/samples/Citation Links.txt` and identify (a) learnings, (b) code improvements, (c) realistic features to add. Below are the V0.28+ candidates I'd recommend you file as `B-XXX` items, ordered by priority. **CIO approved the framing** ("send this to the pm as backlog ideas") -- they're CIO-blessed for backlog entry; you decide sizing + scheduling.

Repos researched (all on github.com):
1. `brendan-w/python-OBD` -- the library we already depend on
2. `BITSREAMxLABs/LiveGauge-LITE` -- pygame gauge dashboard
3. `brian03079/piObdDashboard` -- web-based multi-sensor dashboard
4. `Bipra09/Anomaly-Detection-in-smart-cities` -- LLM-prompt anomaly detection

Full report sits in this session's transcript; the 3 highest-value extractions follow.

---

### Candidate B-083 (suggested) -- Mahalanobis-distance baseline scoring in Spool

**Source:** `Bipra09/Anomaly-Detection-in-smart-cities` (their approach is naive, but the "what you should do instead" pointer surfaced this technique)

**What it does:** add rigorous quantitative grounding to Spool's drive-grading layer. Compute the pre-mod-baseline mean + covariance once (we have 4 captures: drives 6/7/8/11 in `offices/tuner/knowledge.md`'s pre-mod shelf), then for each new drive emit (a) a per-metric Z-score and (b) an overall multivariate Mahalanobis distance with confidence interval.

**Why this is the right anomaly technique for our data:**
- Zero ML training required -- just `numpy.cov()` and a closed-form distance formula
- Captures multivariate structure (e.g., "this AFR is fine in isolation but anomalous *given* this RPM + load")
- Cheap to compute (microseconds per drive)
- Interpretable -- Z-scores per metric directly answer CIO's tuning questions like "is this drive's average AFR statistically different from baseline?"
- Drops directly into Spool's existing Ollama prompt pipeline as a numeric prefix the LLM can reference

**Sizing:** S-M (one story).
**Dependencies:** numpy (already a dep). No new packages.
**Priority recommendation:** HIGH for V0.28.0.

---

### Candidate B-084 (suggested) -- Pre-flight PID probe + opt-in additional PIDs

**Source:** `brendan-w/python-OBD` (we use ~10 of the 90 standard PIDs the library supports)

**Specific PIDs worth opt-in if the 2G 4G63 ECM supports them:**
- `OIL_TEMP` (PID 0x5C) -- directly useful for turbo tuning + thermal-runaway warnings
- `FUEL_RATE` (PID 0x5E) -- enables real-time fuel-consumption + instant-MPG readout on the display
- `FUEL_RAIL_PRESSURE` (PID 0x22/0x23) -- direct knock-margin / lean-condition indicator on E85
- `ETHANOL_PERCENT` (PID 0x52) -- if the ECM supports it, automates pump-gas/E85 dual-map switching detection
- `AMBIENT_AIR_TEMP` (PID 0x46) -- better cold-start semantics than IAT-at-startup
- `ABSOLUTE_LOAD` (PID 0x43) -- alternative to MAF-derived load; more accurate at WOT

**Workflow:** one-time probe session (US-199 supported-PID probe infrastructure already exists) on the 2G ECM to determine which of the six PIDs return real values vs `null` / `not supported`. Then file individual stories for each supported PID with a writer + display + Spool prompt update.

**Sizing:** S for the probe session. Each adopted PID is S-M depending on Spool integration scope.
**Dependencies:** none (`python-obd` already supports them; we just need to add to the poll list).
**Priority recommendation:** MEDIUM for V0.28.x patch sprint -- low-risk incremental wins.

---

### Candidate B-085 (suggested) -- BNO055 IMU sensor (G-force / acceleration / vehicle attitude)

**Source:** `brian03079/piObdDashboard` (they ship a 9-DOF IMU alongside OBD)

**What it does:** adds a fundamentally new signal class our project does not have today -- lateral G's during cornering, longitudinal G's for 0-60 / hard-braking, vehicle attitude (pitch/roll/yaw). Highly relevant for a turbocharged performance car.

**Tuning-grade applications:**
- 0-60 measurement (longitudinal G integrated over time)
- Lateral G correlated with fuel-trim swing during cornering (catches fuel-pickup issues)
- Brake-G events as thermal-warning trigger (hard braking heats brake fluid + rotors fast)
- Launch-G correlation with timing-pull events (catches knock-on-launch)

**Hardware:** Adafruit BNO055 board ~$25, I2C bus (we already have I2C infrastructure for the MAX17048 fuel gauge + display touch). Same i2c_client pattern.

**Sizing:** L (1 sprint). Hardware install (1 day) + new `imu_sensor.py` reader + new `imu_data` table + Pi-to-server sync wiring + Spool prompt updates to consume the new signal.

**Dependencies:** Adafruit BNO055 library; physical hardware purchase + install.

**Priority recommendation:** MEDIUM for V0.28.x or V0.29.0 feature sprint. Genuinely new signal class but not bug-fix urgent.

---

## Lower-priority candidates worth noting but probably not filing yet

- **GPS module (~$30)** for route logging + speedo cross-check + geofencing (auto-WiFi-on at home). Similar pattern to B-085. Useful but not as tuning-load-bearing as IMU. LOW priority unless CIO surfaces a specific use case.
- **Phone-viewable companion web UI** (Flask + Socket.io shim mirroring our display state). LOW priority -- our pygame display is already invested; adding a web shim is parallel work, not strictly an improvement.
- **JSON-driven color-zone config** (LiveGauge-LITE's pattern) -- moves theme thresholds out of `theme.py` into config files for end-user tuning without code deploys. LOW priority -- nice-to-have, no current pain point.
- **Isolation Forest / LSTM autoencoder anomaly detection** -- B-083's bigger siblings. DEFER until we have months of post-mod driving data to train against. Premature now.

---

## What I'd appreciate from PM-side

1. Acknowledge V0.27.10 is ready for deploy. Run `/sprint-deploy-pm` when convenient.
2. File the suggested B-083 / B-084 / B-085 (or rename to whatever numbers you assign) as backlog entries with the framings above. Or push back on any framing you disagree with.
3. Schedule B-083 (Mahalanobis) for the next feature sprint -- it's the highest info-value, lowest-risk addition of the three.

Ack expected: V0.27.10 deploy-routing confirmation + which (if any) of the three candidates you're going to file as proper B-XXX items.

-- Ralph (Rex)
