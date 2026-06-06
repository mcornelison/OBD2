# Phase 2 Data Architecture (ECMLink) — reference

> Extracted from `specs/architecture.md` §17–§18 on 2026-06-01 to keep the main
> architecture spec focused on the implemented system. **Phase 2 = ECMLink
> integration (planned summer 2026) — design only, not yet implemented.**
> Content is verbatim from the main spec at extraction time.

## 17. ECMLink Data Architecture (Phase 2)

### Overview

Phase 2 replaces OBD-II as the primary data source with ECMLink V3, which communicates directly with the 4G63 ECU via Mitsubishi's proprietary MUT protocol at **15,625 baud**. This delivers ~10x the effective sample rate of OBD-II Bluetooth, unlocking parameters critical for tuning that are invisible to standard OBD-II (knock count, wideband AFR, injector duty cycle, true boost).

**Status**: Design only — blocked on ECMLink V3 hardware installation (Summer 2026).

OBD-II (Phase 1) continues running alongside ECMLink for emissions-relevant parameters and as a fallback data source.

### 17.1 ECMLink Parameter Schema (15 Priority Parameters)

| # | Parameter | Data Type | Unit | Sample Rate | Channel Name | Priority Tier |
|---|-----------|-----------|------|-------------|--------------|---------------|
| 1 | Wideband AFR | float | ratio | 20 Hz | `WIDEBAND_AFR` | ECM-1 (Safety) |
| 2 | Knock Count | int | count | 20 Hz | `KNOCK_COUNT` | ECM-1 (Safety) |
| 3 | Knock Sum | int | count | 20 Hz | `KNOCK_SUM` | ECM-1 (Safety) |
| 4 | Boost/MAP | float | psi | 20 Hz | `BOOST_MAP` | ECM-1 (Safety) |
| 5 | Timing Advance | float | degrees | 20 Hz | `TIMING_ADV` | ECM-1 (Safety) |
| 6 | RPM | int | rpm | 20 Hz | `RPM` | ECM-1 (Safety) |
| 7 | TPS | float | percent | 20 Hz | `TPS` | ECM-1 (Safety) |
| 8 | Injector Duty Cycle | float | percent | 10 Hz | `INJECTOR_DC` | ECM-2 (Performance) |
| 9 | Target AFR | float | ratio | 10 Hz | `TARGET_AFR` | ECM-2 (Performance) |
| 10 | STFT | float | percent | 10 Hz | `STFT` | ECM-2 (Performance) |
| 11 | Coolant Temp | float | fahrenheit | 5 Hz | `COOLANT_TEMP` | ECM-3 (Monitoring) |
| 12 | IAT | float | fahrenheit | 5 Hz | `IAT` | ECM-3 (Monitoring) |
| 13 | Ethanol Content | float | percent | 1 Hz | `ETHANOL_CONTENT` | ECM-4 (Background) |
| 14 | LTFT | float | percent | 1 Hz | `LTFT` | ECM-4 (Background) |
| 15 | Barometric Pressure | float | kPa | 0.5 Hz | `BARO_PRESSURE` | ECM-5 (Slow) |

### 17.2 Sample Rate Tiers

Mirrors the Phase 1 tiered polling concept but at ECMLink speeds:

| Tier | Rate | Parameters | Samples/sec | Rationale |
|------|------|------------|-------------|-----------|
| ECM-1 (Safety) | 20 Hz | AFR, Knock Count, Knock Sum, Boost, Timing, RPM, TPS | 140 | Knock and detonation detection requires high-frequency data |
| ECM-2 (Performance) | 10 Hz | Injector DC, Target AFR, STFT | 30 | Fueling health — important but slower-moving |
| ECM-3 (Monitoring) | 5 Hz | Coolant Temp, IAT | 10 | Thermal parameters change slowly |
| ECM-4 (Background) | 1 Hz | Ethanol Content, LTFT | 2 | Stable values that rarely change mid-drive |
| ECM-5 (Slow) | 0.5 Hz | Barometric Pressure | 0.5 | Ambient — changes only with altitude |
| **Total** | | **15 parameters** | **~182.5** | **~657K samples/hr** |

### 17.3 Database Schema

Three new tables, separate from Phase 1 OBD-II tables. The `ecmlink_data` table follows the same EAV (Entity-Attribute-Value) pattern as `realtime_data` for consistency, but is kept separate to avoid mixing data sources and to allow independent retention policies and indexing.

#### Table: `ecmlink_sessions`

Tracks ECMLink logging sessions (one per ignition-on-to-off cycle or manual start/stop).

```sql
CREATE TABLE IF NOT EXISTS ecmlink_sessions (
    session_id TEXT PRIMARY KEY,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    serial_port TEXT NOT NULL,
    baud_rate INTEGER NOT NULL DEFAULT 15625,
    parameters_logged TEXT,
    total_samples INTEGER DEFAULT 0,
    profile_id TEXT,
    notes TEXT,
    CONSTRAINT FK_ecmlink_sessions_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
```

| Column | Purpose |
|--------|---------|
| `session_id` | UUID or timestamp-based ID |
| `serial_port` | e.g., `/dev/ttyUSB0` on Pi |
| `baud_rate` | MUT protocol speed (15,625 default) |
| `parameters_logged` | JSON array of channel names active this session |
| `total_samples` | Running count, updated on session close |
| `profile_id` | Links to active tuning profile |

#### Table: `ecmlink_parameters`

Parameter registry — metadata for each ECMLink channel. Populated once, referenced by ingestion pipeline.

```sql
CREATE TABLE IF NOT EXISTS ecmlink_parameters (
    name TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK(data_type IN ('float', 'int')),
    unit TEXT NOT NULL,
    sample_rate_hz REAL NOT NULL,
    tier TEXT NOT NULL,
    description TEXT,
    safe_range_min REAL,
    safe_range_max REAL
);
```

| Column | Purpose |
|--------|---------|
| `name` | Channel name (e.g., `KNOCK_COUNT`) — matches `ecmlink_data.parameter_name` |
| `data_type` | `float` or `int` — guides display formatting |
| `sample_rate_hz` | Target sample rate for this parameter |
| `tier` | `ECM-1` through `ECM-5` — scheduling tier |
| `safe_range_min/max` | Optional bounds for alert evaluation |

#### Table: `ecmlink_data`

Time-series storage for all ECMLink readings. EAV pattern consistent with `realtime_data`.

```sql
CREATE TABLE IF NOT EXISTS ecmlink_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    parameter_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    session_id TEXT,
    profile_id TEXT,
    CONSTRAINT FK_ecmlink_data_session FOREIGN KEY (session_id)
        REFERENCES ecmlink_sessions(session_id)
        ON DELETE SET NULL,
    CONSTRAINT FK_ecmlink_data_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
```

#### Indexes

```sql
CREATE INDEX IX_ecmlink_data_timestamp ON ecmlink_data(timestamp);
CREATE INDEX IX_ecmlink_data_session ON ecmlink_data(session_id);
CREATE INDEX IX_ecmlink_data_param_timestamp ON ecmlink_data(parameter_name, timestamp);
CREATE INDEX IX_ecmlink_sessions_start_time ON ecmlink_sessions(start_time);
```

The compound index `IX_ecmlink_data_param_timestamp` is critical for the most common query pattern: "give me all readings of parameter X between time A and time B."

#### ER Diagram (Phase 2 additions)

```
┌─────────────────────────┐
│   ecmlink_parameters    │
├─────────────────────────┤
│ name (PK)               │
│ display_name            │
│ data_type               │
│ unit                    │
│ sample_rate_hz          │
│ tier                    │
│ description             │
│ safe_range_min          │
│ safe_range_max          │
└─────────────────────────┘

┌─────────────────────────┐     ┌─────────────────────────┐
│   ecmlink_sessions      │     │      profiles           │
├─────────────────────────┤     ├─────────────────────────┤
│ session_id (PK)         │     │ id (PK)                 │
│ start_time              │──┐  │ name                    │
│ end_time                │  │  │ ...                     │
│ serial_port             │  │  └──────────┬──────────────┘
│ baud_rate               │  │             │
│ parameters_logged       │  │  ┌──────────▼──────────────┐
│ total_samples           │  │  │     ecmlink_data        │
│ profile_id (FK)─────────│──┤  ├─────────────────────────┤
│ notes                   │  │  │ id (PK)                 │
└─────────────────────────┘  │  │ timestamp               │
                             └──│ session_id (FK)         │
                                │ parameter_name          │
                                │ value                   │
                                │ unit                    │
                                │ profile_id (FK)─────────│
                                └─────────────────────────┘
```

### 17.4 Ingestion Interface

ECMLink serial data enters the system through a dedicated ingestion pipeline, separate from the OBD-II Bluetooth path.

#### Data Flow

```
ECMLink V3 (ECU)
    │
    │  MUT Protocol (15,625 baud, serial)
    ▼
USB-Serial Adapter (/dev/ttyUSB0)
    │
    ▼
┌────────────────────────────────┐
│  ECMLink Serial Reader         │
│  (dedicated thread)            │
│                                │
│  1. Open serial port           │
│  2. Parse MUT protocol frames  │
│  3. Timestamp each sample      │
│  4. Route to sample buffer     │
└──────────┬─────────────────────┘
           │
           ▼
┌────────────────────────────────┐
│  Sample Buffer                 │
│  (in-memory ring buffer)       │
│                                │
│  - Capacity: 1000 samples      │
│  - Batch flush threshold: 100  │
│  - Max flush interval: 500ms   │
└──────────┬─────────────────────┘
           │
           ▼
┌────────────────────────────────┐
│  Batch Writer                  │
│  (separate thread)             │
│                                │
│  1. Dequeue batch from buffer  │
│  2. BEGIN TRANSACTION          │
│  3. INSERT batch into          │
│     ecmlink_data               │
│  4. COMMIT                     │
│  5. Update session counters    │
└──────────┬─────────────────────┘
           │
           ▼
      SQLite (WAL mode)
```

#### Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Separate table** (`ecmlink_data` not `realtime_data`) | Different data source, different sample rates (30x more volume), independent retention needs. Clean Phase 1/Phase 2 isolation. |
| **EAV pattern** (not wide table) | Consistent with Phase 1. Adding new ECMLink parameters requires zero schema changes. Sparse sampling (mixed rates) doesn't waste space on NULLs. |
| **Batch writes** (not per-sample) | At ~182 samples/sec, individual INSERTs would be ~182 transactions/sec. Batching 100 samples per transaction keeps SQLite happy and reduces I/O. |
| **Ring buffer** (not unbounded queue) | Memory-bounded on Pi 5 (8GB). If writer falls behind, oldest unwritten samples are dropped — better to lose old data than OOM. |
| **Session tracking** | ECMLink logging sessions map to ignition cycles. Session metadata enables "show me all data from drive #47" queries and cleanup. |
| **Dedicated threads** (reader + writer) | Serial I/O blocks on frame arrival; database I/O blocks on disk. Separating them keeps both responsive. |

#### Serial Protocol Notes

- **Baud rate**: 15,625 (MUT protocol, fixed)
- **Connection**: USB-to-serial adapter, typically `/dev/ttyUSB0` on Pi
- **Frame format**: ECMLink-specific binary frames (documented at ecmlink.com)
- **Handshake**: ECMLink software initiates MUT communication; our reader taps into the serial stream
- **Error handling**: CRC/checksum validation per frame. Invalid frames are logged and discarded, not retried.

#### Configuration (obd_config.json, future)

```json
{
    "ecmlink": {
        "enabled": false,
        "serialPort": "${ECMLINK_SERIAL_PORT:/dev/ttyUSB0}",
        "baudRate": 15625,
        "batchSize": 100,
        "maxFlushIntervalMs": 500,
        "bufferCapacity": 1000,
        "parameters": [
            {"name": "WIDEBAND_AFR", "enabled": true, "tier": "ECM-1"},
            {"name": "KNOCK_COUNT", "enabled": true, "tier": "ECM-1"},
            {"name": "KNOCK_SUM", "enabled": true, "tier": "ECM-1"},
            {"name": "BOOST_MAP", "enabled": true, "tier": "ECM-1"},
            {"name": "TIMING_ADV", "enabled": true, "tier": "ECM-1"},
            {"name": "RPM", "enabled": true, "tier": "ECM-1"},
            {"name": "TPS", "enabled": true, "tier": "ECM-1"},
            {"name": "INJECTOR_DC", "enabled": true, "tier": "ECM-2"},
            {"name": "TARGET_AFR", "enabled": true, "tier": "ECM-2"},
            {"name": "STFT", "enabled": true, "tier": "ECM-2"},
            {"name": "COOLANT_TEMP", "enabled": true, "tier": "ECM-3"},
            {"name": "IAT", "enabled": true, "tier": "ECM-3"},
            {"name": "ETHANOL_CONTENT", "enabled": true, "tier": "ECM-4"},
            {"name": "LTFT", "enabled": true, "tier": "ECM-4"},
            {"name": "BARO_PRESSURE", "enabled": true, "tier": "ECM-5"}
        ]
    }
}
```

### 17.5 Phase 1 / Phase 2 Coexistence

Both data sources run simultaneously. OBD-II continues providing emissions-relevant data and acts as a fallback if the ECMLink serial connection drops.

| Aspect | Phase 1 (OBD-II) | Phase 2 (ECMLink) |
|--------|-------------------|-------------------|
| Protocol | ELM327 over Bluetooth | MUT over USB serial |
| Sample rate | ~1 Hz per parameter | 0.5–20 Hz per parameter |
| Data table | `realtime_data` | `ecmlink_data` |
| Parameters | 16 standard PIDs | 15 priority + expandable |
| Alert thresholds | `tieredThresholds` in config | Shared alert system (future) |
| Primary use | Emissions monitoring, baseline | Tuning, knock detection, AFR |

Parameters that overlap (RPM, Coolant Temp, STFT, Timing Advance, IAT) will be sourced from ECMLink when available, with OBD-II as fallback. The alert system will be extended to accept either data source via a common `(parameter_name, value, timestamp)` tuple interface.

---

## 18. Data Volume Architecture (Phase 2)

### Overview

Phase 2 (ECMLink) generates ~30x the data volume of Phase 1 (OBD-II). This section documents storage estimates, retention policies, and sync strategy to ensure the system handles ECMLink data volumes across both Pi 5 (edge) and Chi-Srv-01 (server) without running out of disk, degrading query performance, or creating unsustainable sync loads.

**Status**: Design only — runtime implementation deferred until ECMLink hardware installation (Summer 2026).

### 18.1 Data Volume Estimates

#### Phase 1 (OBD-II via Bluetooth)

| Metric | Value | Derivation |
|--------|-------|------------|
| Effective sample rate | ~5 reads/sec | 12 PIDs across 4 tiers; Bluetooth latency reduces theoretical ~6/sec |
| Rows per hour | ~18,000 | 5 × 3,600 |
| Rows per 2-hour drive | ~36,000 | |
| Rows per season (~40 hrs driving) | ~720,000 | Summer-only car, weekend use |
| Rows per year (365-day retention) | ~720,000 | Same — car only runs in season |

#### Phase 2 (ECMLink via Serial)

| Metric | Value | Derivation |
|--------|-------|------------|
| Theoretical sample rate | ~182.5 reads/sec | 15 parameters across 5 tiers (Section 17.2) |
| Effective sample rate | ~150 reads/sec | Serial bandwidth constraint: 15,625 baud ÷ ~10 bits/byte = ~1,562 bytes/sec. MUT frame overhead (~3-4 bytes/param + framing) limits practical throughput |
| Rows per hour | ~540,000 | 150 × 3,600 |
| Rows per 2-hour drive | ~1,080,000 | |
| Rows per season (~40 hrs) | ~21,600,000 | |
| Phase 1 + Phase 2 combined/season | ~22,320,000 | Both run simultaneously (Section 17.5) |

#### Serial Bandwidth Constraint Detail

```
MUT Protocol: 15,625 baud, 8N1
Effective byte rate: ~1,562 bytes/sec
Estimated bytes per parameter read: ~8-10 bytes (address + response + framing)
Max parameters per second: ~1,562 / 9 ≈ 173 reads/sec
Accounting for handshake/sync overhead: ~150 reads/sec practical
```

The ~150 reads/sec practical rate drives all Phase 2 storage and bandwidth estimates. The theoretical 182.5/sec from Section 17.2 assumes zero protocol overhead.

### 18.2 Row Size Estimates

Both `realtime_data` (Phase 1) and `ecmlink_data` (Phase 2) use the same EAV schema pattern.

#### Per-Row Storage Breakdown

| Component | Bytes | Notes |
|-----------|-------|-------|
| `id` (INTEGER PK) | 8 | AUTOINCREMENT 64-bit |
| `timestamp` (DATETIME) | 8 | Stored as real/text (~19-23 chars) |
| `parameter_name` (TEXT) | ~16 | Avg channel name length (e.g., `KNOCK_COUNT`) |
| `value` (REAL) | 8 | 64-bit float |
| `unit` (TEXT) | ~8 | e.g., `percent`, `psi`, `rpm` |
| `session_id` (TEXT) | ~36 | UUID |
| `profile_id` (TEXT) | ~36 | UUID |
| SQLite row overhead | ~20 | Page headers, cell pointers, free space |
| **Subtotal (data row)** | **~140** | |

#### Index Overhead

| Index | Bytes/entry | Notes |
|-------|-------------|-------|
| `IX_ecmlink_data_timestamp` | ~30 | timestamp + rowid |
| `IX_ecmlink_data_session` | ~50 | session_id (TEXT) + rowid |
| `IX_ecmlink_data_param_timestamp` | ~50 | parameter_name + timestamp + rowid |
| **Subtotal (indexes)** | **~130** | |
| **Total per row (data + indexes)** | **~270 bytes** | |

#### Disk Usage Per Million Rows

| Storage Component | Size |
|-------------------|------|
| Data rows (1M × 140 bytes) | ~140 MB |
| Indexes (1M × 130 bytes) | ~130 MB |
| SQLite overhead (page alignment, free lists) | ~10% |
| **Total per 1M rows** | **~300 MB** |

### 18.3 Pi 5 SQLite Storage Strategy

#### Hardware Context

| Spec | Value |
|------|-------|
| Storage | microSD (64-128 GB typical) or NVMe via HAT |
| RAM | 8 GB |
| SQLite mode | WAL (already configured) |

#### Seasonal Storage Estimate (Pi)

| Data Source | Rows/Season | Size (with indexes) | Notes |
|-------------|-------------|---------------------|-------|
| Phase 1 (`realtime_data`) | ~720K | ~216 MB | 365-day retention (current config) |
| Phase 2 (`ecmlink_data`) | ~21.6M | ~6.5 GB | 90-day retention (new policy) |
| Phase 2 sessions/params | ~200 | <1 MB | Metadata tables |
| WAL file (peak) | — | ~200 MB | WAL grows during batch writes, checkpoints shrink it |
| **Total (one season)** | **~22.3M** | **~7.0 GB** | |

#### Can Pi Store a Full Season?

**Yes.** On a 64 GB microSD card:

| Allocation | Size |
|------------|------|
| OS + system | ~8 GB |
| Application + venv | ~2 GB |
| Logs | ~1 GB |
| OBD-II data (Phase 1, 1 year) | ~0.2 GB |
| ECMLink data (Phase 2, 90-day window) | ~6.5 GB |
| WAL headroom | ~0.5 GB |
| **Total used** | **~18.2 GB** |
| **Remaining** | **~45.8 GB** |
| **Utilization** | **~28%** |

With NVMe (256+ GB), storage is effectively unlimited for this use case.

#### Pi Retention Policy

| Table | Retention | Rationale |
|-------|-----------|-----------|
| `realtime_data` | 365 days | Current config. Low volume (~720K rows/season). Keep for full-season comparison. |
| `ecmlink_data` | 90 days | High volume. 90 days covers the active tuning season (May-September). Older data lives on Chi-Srv-01. |
| `ecmlink_sessions` | 90 days | Tied to ecmlink_data lifecycle. Cascade cleanup. |
| `statistics` | Forever | Aggregated — tiny footprint regardless of retention. |
| `alert_log` | 365 days | Low volume, high diagnostic value. |

**Cleanup Strategy**: Extend the existing `dataRetention` config with an `ecmlinkDataDays` field:

```json
{
    "dataRetention": {
        "realtimeDataDays": 365,
        "ecmlinkDataDays": 90,
        "statisticsRetentionDays": -1,
        "vacuumAfterCleanup": true,
        "cleanupTimeHour": 3
    }
}
```

Cleanup runs at 3 AM (existing `cleanupTimeHour`). For `ecmlink_data`, delete by timestamp:

```sql
DELETE FROM ecmlink_data
WHERE timestamp < datetime('now', '-90 days');

DELETE FROM ecmlink_sessions
WHERE end_time IS NOT NULL
  AND end_time < datetime('now', '-90 days');
```

Run `VACUUM` after cleanup to reclaim disk space (`vacuumAfterCleanup: true`).

#### SQLite Performance at Scale

At 21.6M rows, queries on `ecmlink_data` need index support:

| Query Pattern | Index Used | Expected Performance |
|---------------|-----------|---------------------|
| Parameter X between time A and B | `IX_ecmlink_data_param_timestamp` | <50ms (B-tree seek) |
| All data for session Y | `IX_ecmlink_data_session` | <100ms (session is bounded) |
| Recent N readings | `IX_ecmlink_data_timestamp` | <10ms (index scan from tail) |
| Full table scan | None | ~5-10 sec at 21.6M rows — **avoid** |

WAL mode (already enabled) prevents batch writes from blocking reads during driving. The `PRAGMA journal_size_limit` should be set to cap WAL growth during heavy ECMLink ingestion:

```sql
PRAGMA journal_size_limit = 67108864;  -- 64 MB WAL cap
```

### 18.4 Chi-Srv-01 MariaDB Strategy

#### Hardware Context

| Spec | Value |
|------|-------|
| CPU | i7-5960X (8 cores) |
| RAM | 128 GB |
| Storage | RAID array (multi-TB) |
| Database | MariaDB (`obd2db`) |
| Network | Gigabit Ethernet, same LAN as Pi (10.27.27.0/24) |

#### Retention Policy: Forever

Chi-Srv-01 is the permanent archive. All data synced from Pi is retained indefinitely. This enables:
- Multi-season trend analysis ("has knock behavior changed since injector upgrade?")
- Tuning profile comparison across months/years
- Full diagnostic history for engine health tracking

#### Storage Estimate (Multi-Season)

| Timeframe | ECMLink Rows | Size | Cumulative |
|-----------|-------------|------|------------|
| Season 1 (2026) | 21.6M | ~6.5 GB | 6.5 GB |
| Season 2 (2027) | 21.6M | ~6.5 GB | 13.0 GB |
| Season 3 (2028) | 21.6M | ~6.5 GB | 19.5 GB |
| 5 seasons | 108M | ~32.5 GB | 32.5 GB |
| 10 seasons | 216M | ~65 GB | 65 GB |

With Phase 1 data: add ~0.2 GB/season. Negligible.

At 128 GB RAM and multi-TB disk, Chi-Srv-01 handles 10+ seasons without concern. The InnoDB buffer pool can hold the hot working set entirely in memory.

#### Partitioning Strategy

Partition `ecmlink_data` by **month** using `RANGE` partitioning on `timestamp`. Monthly partitions enable:
- Fast partition pruning on time-range queries (the primary access pattern)
- Efficient bulk archival (detach old partitions to cold storage)
- Manageable backup units (~2-3 GB per active month)

```sql
CREATE TABLE ecmlink_data (
    id BIGINT AUTO_INCREMENT,
    timestamp DATETIME(3) NOT NULL,
    parameter_name VARCHAR(50) NOT NULL,
    value DOUBLE NOT NULL,
    unit VARCHAR(20),
    session_id VARCHAR(36),
    profile_id VARCHAR(36),
    PRIMARY KEY (id, timestamp),
    INDEX IX_ecmlink_data_param_timestamp (parameter_name, timestamp),
    INDEX IX_ecmlink_data_session (session_id)
) ENGINE=InnoDB
PARTITION BY RANGE (TO_DAYS(timestamp)) (
    PARTITION p2026_05 VALUES LESS THAN (TO_DAYS('2026-06-01')),
    PARTITION p2026_06 VALUES LESS THAN (TO_DAYS('2026-07-01')),
    PARTITION p2026_07 VALUES LESS THAN (TO_DAYS('2026-08-01')),
    PARTITION p2026_08 VALUES LESS THAN (TO_DAYS('2026-09-01')),
    PARTITION p2026_09 VALUES LESS THAN (TO_DAYS('2026-10-01')),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);
```

**Partition maintenance**: At season start each year, `ALTER TABLE ... REORGANIZE PARTITION p_future` to add the new season's monthly partitions. Automate via cron or manual DBA task (low frequency — once per year).

#### Indexing for 21M+ Rows

| Index | Columns | Purpose |
|-------|---------|---------|
| PRIMARY KEY | `(id, timestamp)` | Required for RANGE partitioning — timestamp in PK enables partition pruning |
| `IX_ecmlink_data_param_timestamp` | `(parameter_name, timestamp)` | Primary query pattern: "parameter X between time A and B" |
| `IX_ecmlink_data_session` | `(session_id)` | Session-scoped queries: "all data from drive #47" |

**Not indexed**: `profile_id`, `unit` — low-cardinality columns better served by full-partition scans than index maintenance overhead at this volume.

InnoDB buffer pool recommendation: Allocate 64 GB to `innodb_buffer_pool_size` (50% of 128 GB RAM). At 6.5 GB/season, the entire active season's data + indexes fit in memory.

### 18.5 Sync Strategy (Pi → Chi-Srv-01)

#### Network Context

| Spec | Value |
|------|-------|
| WiFi network | DeathStarWiFi (10.27.27.0/24) |
| Pi 5 WiFi | 802.11ac (WiFi 5), ~100-200 Mbps practical |
| Chi-Srv-01 | Gigabit Ethernet to same LAN |
| Effective throughput | ~50-100 Mbps (WiFi bottleneck) |

#### Sync Bandwidth Estimate: 2-Hour ECMLink Drive

| Step | Value |
|------|-------|
| Rows generated | ~1,080,000 (540K/hr × 2) |
| Raw data size | ~1,080,000 × 270 bytes = ~292 MB |
| Compressed (gzip, ~3:1 on text/numeric data) | ~100 MB |
| Transfer time at 50 Mbps | ~16 seconds |
| Transfer time at 100 Mbps | ~8 seconds |
| **Practical estimate (with protocol overhead)** | **~20-30 seconds** |

A full season's sync (21.6M rows, ~6.5 GB raw, ~2.2 GB compressed) takes ~3-6 minutes. This is a one-time bulk transfer if the Pi was offline.

#### Sync Mechanism (Design)

Sync runs post-drive when Pi reconnects to WiFi (garage). The sync pipeline:

```
Pi (SQLite)                              Chi-Srv-01 (MariaDB)
    │                                         │
    │  1. Detect WiFi connection              │
    │  2. Query unsynced rows:                │
    │     SELECT * FROM ecmlink_data          │
    │     WHERE id > last_synced_id           │
    │  3. Batch export to compressed          │
    │     JSON/CSV chunks (10K rows each)     │
    │                                         │
    │  ──── compressed chunks over HTTP ────► │
    │                                         │
    │                   4. Bulk INSERT         │
    │                      (LOAD DATA INFILE  │
    │                       or batch INSERT)  │
    │                   5. Acknowledge receipt │
    │                                         │
    │  ◄──── ack (last_synced_id) ──────────  │
    │                                         │
    │  6. Update local sync watermark         │
    │                                         │
```

**Sync watermark**: Track `last_synced_id` per table in a local `sync_status` table on Pi. This avoids re-sending data after a partial sync.

```sql
-- Pi-side sync tracking
CREATE TABLE IF NOT EXISTS sync_status (
    table_name TEXT PRIMARY KEY,
    last_synced_id INTEGER NOT NULL DEFAULT 0,
    last_sync_time DATETIME,
    target_server TEXT NOT NULL DEFAULT 'chi-srv-01'
);
```

**Conflict resolution**: None needed — Pi is the sole writer, Chi-Srv-01 is append-only archive. No bidirectional sync.

#### Sync Frequency

| Trigger | Behavior |
|---------|----------|
| Post-drive (WiFi reconnect) | Auto-sync unsynced rows. Primary trigger. |
| Nightly (3 AM, with cleanup) | Catch any missed syncs. |
| Manual | `python src/main.py --sync` for on-demand sync. |

### 18.6 Retention Policy Validation

#### Can the 90-day Pi / forever-server policy handle Phase 2 volumes?

| Validation Check | Result | Notes |
|-----------------|--------|-------|
| Pi disk at 90 days (ECMLink) | ~6.5 GB max | Well within 64 GB SD card |
| Pi disk at 90 days (total) | ~7.0 GB max | Phase 1 + Phase 2 + overhead |
| Pi cleanup runtime | <30 sec | DELETE with timestamp index, then VACUUM |
| Chi-Srv-01 at 1 season | ~6.7 GB | Phase 1 + Phase 2, trivial for multi-TB RAID |
| Chi-Srv-01 at 10 seasons | ~67 GB | Fits in RAM buffer pool, no performance concern |
| Sync backlog after 90 days offline | ~6.5 GB / ~2.2 GB compressed | ~3-6 min sync, acceptable |
| WAL size during ECMLink ingestion | ≤64 MB (capped) | Checkpoint keeps WAL bounded |

**Conclusion**: The 90-day Pi retention / forever server retention policy is validated at Phase 2 volumes. No storage constraints on either platform. The main risk is WAL growth during heavy ingestion, mitigated by `PRAGMA journal_size_limit`.

### 18.7 Summary

| Metric | Phase 1 (OBD-II) | Phase 2 (ECMLink) | Combined |
|--------|-------------------|-------------------|----------|
| Sample rate | ~5/sec | ~150/sec | ~155/sec |
| Rows per hour | ~18K | ~540K | ~558K |
| Rows per season | ~720K | ~21.6M | ~22.3M |
| Disk per season (with indexes) | ~216 MB | ~6.5 GB | ~6.7 GB |
| Pi retention | 365 days | 90 days | — |
| Server retention | Forever | Forever | — |
| 2-hr drive sync time | <1 sec | ~20-30 sec | ~30 sec |
| Pi storage headroom (64 GB) | 92% free | 72% free | 72% free |

---
