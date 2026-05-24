# Maintenance Tracking — Design

| Field    | Value                                                              |
|----------|--------------------------------------------------------------------|
| Date     | 2026-05-21                                                         |
| Author   | Spool (Tuning SME)                                                 |
| Status   | Design — awaiting CIO sign-off before backlog grooming intake      |
| Theme    | Sub-thread B of broader brainstorm (data we don't collect, owner-helpful) |
| Scope    | V1.0 MVP (5 items, one per category + 1 critical) → V1.0 Full (catalog expansion) → V2+ |
| Branch   | sprint/sprint41-bugfixes-V0.27.17 (work targets V0.30+ post chain merge) |

---

## 1. Overview + Scope

### What we're building

A maintenance-tracking subsystem for the Eclipse OBD-II project. Server-authoritative records of every service interval, wear item, regulatory date, and one-off event in the car's life. A reminder engine that computes what's due (by date + by mileage) and surfaces alerts on the Pi parked-mode tile + Telegram push + CLI query. Entry via CLI (Spool/CIO discipline) + Telegram conversational (B-099 infrastructure). Bulk YAML import seeds 28 years of historical records in one shot.

### V1.0 MVP — cross-category vertical slice (5 items)

The MVP slice proves all four category types end-to-end plus the critical-tier lead-time path. Once these work, V1 Full expansion is mechanical (more catalog rows, same code).

| Category | MVP catalog item | What it proves |
|---|---|---|
| `service_interval` (medium) | **Oil change** | Both mileage-based + time-based reminders; the most-common service mental model |
| `service_interval` (critical) | **Timing belt** | Recurring service + critical-tier lead-time test (180-day / 5,000-mi warning window); rich `details_json` (parts list, shop, labor hours) |
| `wear_item` | **Brake pads (front)** | Condition-based tracking; measurement-bearing event (thickness in `details_json`) |
| `regulatory` | **Registration renewal** | Pure calendar-based reminder; simplest path |
| `event_log` | **Modification install** | One-off events with no schedule; tests variadic `details_json` flexibility |

### V1.0 Full — expanded catalog (deferred; characterized)

Expand `maintenance_items` catalog with full common-item set — same code paths, just more catalog rows:

- **Service intervals**: oil filter, air filter, cabin air, coolant flush, brake fluid flush, transmission fluid (MTL/gear oil), spark plugs, serpentine belt, power steering fluid, front diff / transaxle (FWD 2G), fuel filter
- **Wear items**: rear brake pads, rotors front/rear, tires (tread depth + age + rotation), battery (age + load test), wiper blades, suspension components, exhaust system
- **Regulatory**: emissions inspection (IL-EPA OBD-II biennial in Cook), insurance renewal, vehicle inspection
- **Event log types**: repair events, diagnostic visits (dyno, alignment, tuning), track day / autocross participation, accident / damage history

### V2+ deferred features

- **Web UI** (Flask/FastAPI mini-app) — typed forms on laptop/phone; deferred because CLI + Telegram covers v1 needs cheaply
- **Telegram proactive mileage prompts** — periodic bot nudge "what's your odometer reading?"; rides B-099 infrastructure
- **Email reminders** (SMTP) — out of scope; Telegram + Pi tile + CLI cover v1
- **MrSpool RAG integration** — V0.34+ horizon (B-094); consumes maintenance records as RAG context; JSON output schema designed to be compatible from day one
- **Multi-vehicle support** — single-vehicle by design; if needed, future migration adds `vehicle_id` column
- **Cost rollup / TCO dashboard** — out of scope; v1 stores cost as lightweight field; SQL query suffices
- **Automated measurement-threshold checks** for wear items — v1 shows last measurement; CIO eyeballs against thresholds; v2 can automate
- **Receipt scan attachments** — `attachments_json` reserved column; v2 wires actual file storage

### Constraints

- **B-104 server-authoritative pattern** in force: server is sole writer; Pi gets read-only mirror via sync-back (same pattern as topic A's `anomaly_log`)
- **Rides topic A's sync-back wiring** — both topics extend the same `/api/v1/sync` response payload with new keys; single infrastructure change, two consumers
- **Single-vehicle scope** — no multi-tenancy concerns; schema stays simple
- **2G Eclipse has no OBD-II odometer PID** — mileage subsystem REQUIRED for any mileage-based reminders; v1 includes manual + speed-integration hybrid
- **Targets V0.30+ per 2026-05-14 phasing** (Phase-3 engagement); orthogonal to V0.27 chain merge and topic A anomaly engine
- **No real-time engine-data interaction** — purely metadata + reminders; can ship independently of anomaly engine

---

## 2. Schema + Data Model

### Table 1: `maintenance_items` — the catalog

Catalog of WHAT we track. Each row defines an item + its schedule. Rare writes; many reads.

```sql
CREATE TABLE maintenance_items (
    item_id              VARCHAR(64)  PRIMARY KEY,
    category             VARCHAR(32)  NOT NULL,
    name                 VARCHAR(128) NOT NULL,
    interval_miles       INTEGER      NULL,
    interval_days        INTEGER      NULL,
    criticality          VARCHAR(16)  NOT NULL,
    notes                TEXT         NULL,
    active               BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (category IN ('service_interval', 'wear_item', 'regulatory', 'event_log')),
    CHECK (criticality IN ('low', 'medium', 'high', 'critical'))
);
CREATE INDEX idx_maintenance_items_category ON maintenance_items(category, active);
```

Per-category interval semantics:

| Category | `interval_miles` | `interval_days` | Meaning of "due" |
|---|---|---|---|
| service_interval | both required | both required | Next service due |
| wear_item | required | optional | Next inspection due |
| regulatory | NULL | required | Next renewal due |
| event_log | NULL | NULL | No recurring schedule (no "due" semantic) |

### Table 2: `maintenance_events` — the occurrences

Each row = one occurrence of work on a tracked item. The append-only history.

```sql
CREATE TABLE maintenance_events (
    id                   INTEGER      PRIMARY KEY AUTOINCREMENT,
    item_id              VARCHAR(64)  NOT NULL REFERENCES maintenance_items(item_id),
    performed_at         DATETIME     NOT NULL,
    performed_mileage    INTEGER      NULL,
    cost_cents           INTEGER      NULL,
    performed_by         VARCHAR(64)  NULL,
    notes                TEXT         NULL,
    details_json         TEXT         NULL,
    attachments_json     TEXT         NULL,
    confidence           VARCHAR(16)  NOT NULL DEFAULT 'high',
    source               VARCHAR(32)  NOT NULL DEFAULT 'manual',
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (confidence IN ('high', 'medium', 'low')),
    CHECK (source IN ('manual', 'telegram', 'import', 'auto'))
);
CREATE INDEX idx_maintenance_events_item_perf ON maintenance_events(item_id, performed_at DESC);
```

`details_json` content per category (example shapes):

**`service_interval`** — usually `{}`. For timing belt:
```json
{
  "event_type": "service_milestone",
  "parts": ["Mitsubishi OEM timing belt", "OEM tensioner", "Gates water pump", "OEM idler pulley"],
  "labor_hours": 12,
  "shop_invoice_ref": "INV-2022-0615"
}
```

**`wear_item`** — condition measurement:
```json
{
  "measurement_field": "thickness",
  "measurement_value": 7,
  "measurement_unit": "mm",
  "inspector_notes": "front-left lip developing"
}
```

**`regulatory`** — usually `{}`.

**`event_log`** — variadic per event subtype:
```json
{
  "event_type": "modification",
  "parts": ["BlitzkriegMotors aluminum BOV", "OEM-spec recirculation pipe"],
  "labor_hours": 1.5,
  "shop_invoice_ref": "INV-2024-0312"
}
```

JSON queried via MariaDB `JSON_EXTRACT(details_json, '$.event_type')` when needed.

`confidence` semantic:
- `high` — verified (CIO knows + has receipt)
- `medium` — remembered but no receipt
- `low` — best-guess from indirect signals (prior-owner records, age-based assumption)

`source` semantic: tracks origin for audit (`manual` / `telegram` / `import` / `auto`).

### Table 3: `vehicle_mileage_log` — mileage subsystem

The hybrid manual + estimated mileage track. Server-authoritative; Pi mirror updates via sync.

```sql
CREATE TABLE vehicle_mileage_log (
    id                       INTEGER      PRIMARY KEY AUTOINCREMENT,
    recorded_at              DATETIME     NOT NULL,
    mileage                  INTEGER      NOT NULL,
    source                   VARCHAR(16)  NOT NULL,
    drive_id                 INTEGER      NULL,
    delta_miles_since_prior  REAL         NULL,
    confidence               VARCHAR(16)  NOT NULL DEFAULT 'high',
    notes                    TEXT         NULL,
    created_at               DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (source IN ('manual', 'estimated', 'import')),
    CHECK (confidence IN ('high', 'medium', 'low'))
);
CREATE INDEX idx_mileage_recorded ON vehicle_mileage_log(recorded_at DESC);
CREATE INDEX idx_mileage_source ON vehicle_mileage_log(source, recorded_at DESC);
```

**Mileage subsystem algorithm — `current_mileage_estimate(now)`:**
1. Find latest `source='manual'` row (call it `M`)
2. Sum all `delta_miles_since_prior` from `source='estimated'` rows where `recorded_at > M.recorded_at`
3. Return `M.mileage + sum`

**On new manual entry**: insert manual row; log delta vs estimate at that moment for drift detection. Estimated rows are NEVER auto-rewritten (history immutable).

**On drive end**: server post-drive compute (rides US-350 trigger) integrates `realtime_data.VEHICLE_SPEED × Δt` to get `drive_distance_miles`; inserts new `source='estimated'` row.

**Drift detection**: on each new manual entry, log the manual-vs-estimate delta. If drift >5% between manual entries spanning ≥90 days, surface warning in `status` output.

### Table 4: `maintenance_import_log` — audit trail

```sql
CREATE TABLE maintenance_import_log (
    id              INTEGER      PRIMARY KEY AUTOINCREMENT,
    imported_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    file_path       VARCHAR(256) NOT NULL,
    file_hash       VARCHAR(64)  NOT NULL,
    items_created   INTEGER      NOT NULL DEFAULT 0,
    items_updated   INTEGER      NOT NULL DEFAULT 0,
    items_skipped   INTEGER      NOT NULL DEFAULT 0,
    events_created  INTEGER      NOT NULL DEFAULT 0,
    mileage_created INTEGER      NOT NULL DEFAULT 0,
    errors_count    INTEGER      NOT NULL DEFAULT 0,
    mode            VARCHAR(16)  NOT NULL,
    summary_json    TEXT         NULL,
    CHECK (mode IN ('strict', 'lenient', 'dry-run'))
);
```

Same `file_hash` re-imported = idempotent no-op (records attempt but writes nothing). Audit trail survives even if YAML file is later deleted.

### Derived computations (computed on-demand; not stored)

| Computation | Logic |
|---|---|
| `current_mileage` | `vehicle_mileage_log` algorithm above |
| `last_event(item_id)` | Latest `maintenance_events` row for that item |
| `next_due_date(item_id)` | `last_event.performed_at + interval_days` (NULL if no `interval_days` or no events) |
| `next_due_miles(item_id)` | `last_event.performed_mileage + interval_miles` (NULL if no `interval_miles`, no events, or no mileage on last event) |
| `due_status(item_id)` | UP-TO-DATE / DUE-SOON / OVERDUE / NO-HISTORY (see Section 4) |

### Pi-side mirror (B-104 read-only consumer)

Pi `database_schema.py` gains four new `SCHEMA_*` constants matching server shape exactly (3 main tables + import log). Pi tables read-only by construction; enforce via Python-level tripwire:

```python
class MaintenanceItemsMirror:
    """Pi-side read-only mirror of server maintenance_items.
    
    Writes happen ONLY via sync-back payload consumption.
    Any other write attempt raises -- enforces B-104 authority model.
    """
    def insert_user_authored(self, ...):
        raise NotImplementedError(
            "Pi-side direct writes to maintenance_items are forbidden. "
            "Server is sole writer per B-104. Use server CLI or Telegram."
        )
```

Mirrors Atlas's Sprint 39 `UpsMonitor.getPowerSource() NotImplementedError` pattern.

### Schema deltas vs current state

All four tables are NEW. No modifications to existing tables. Migration via standard Sprint-style migration (Sprint 39/40 cadence). Schema parity discipline (Atlas A-4 watch item) — Pi-side `database_schema.py` mirrors server shape exactly.

---

## 3. Architecture + Data Flow

### Compute location

Server-side per B-104. Pi is read-only consumer. Topic B rides topic A's same sync-back wiring extension to `/api/v1/sync` response payload.

### Data flow scenarios

```
SCENARIO 1 — CLI entry
─────────────────────────
   CIO ssh ──► python -m server.cli.maintenance log --item oil_change ...
                  │
                  ▼
              event_logger.log_event() ──► INSERT maintenance_events
                                            │
                                            ▼
                                    (next sync-back to Pi includes new row)

SCENARIO 2 — Telegram conversational entry
────────────────────────────────────────────
   CIO Telegram ──► B-099 bot infra ──► telegram_handlers.MaintenanceConvFlow
                                            │
                                            ▼
                                        event_logger.log_event(source='telegram')
                                            │
                                            ▼
                                        INSERT maintenance_events

SCENARIO 3 — Bulk historical seed
───────────────────────────────────
   seed_maintenance.yaml ──► python -m server.cli.maintenance import --file ...
                              │
                              ▼
                          seed_loader.load_and_validate() ──► 3-table batch INSERT
                                                                  │
                                                                  ▼
                                                          INSERT maintenance_import_log
                                                                  │
                                                                  ▼
                                                          (sync-back to Pi)

SCENARIO 4 — Drive ends → automatic mileage estimate
─────────────────────────────────────────────────────
   Pi drive end ──► sync to server ──► US-350 drive_summary_compute (existing)
                                            │
                                            ▼
                                    NEW: mileage_estimator.append_drive_estimate(drive_id)
                                            │  reads VEHICLE_SPEED × Δt
                                            ▼
                                    INSERT vehicle_mileage_log (source='estimated')

SCENARIO 5 — Reminder engine query (3 consumers, 1 algorithm)
───────────────────────────────────────────────────────────────
   Consumer request ──► reminder_engine.compute_due_status_all()
                          │
                          ├─► For each active maintenance_items row:
                          │     last_event = latest maintenance_events for item
                          │     next_due_date = last_event.performed_at + interval_days
                          │     next_due_miles = last_event.performed_mileage + interval_miles
                          │     current_mileage = mileage_estimator.current()
                          │     due_status = classify(now, current_mileage, due dates)
                          ▼
                      Return list of {item, due_status, time_remaining, miles_remaining}
```

### Module layout

```
src/server/maintenance/                NEW package
├── __init__.py
├── models.py                          # SQLAlchemy ORM: MaintenanceItem, MaintenanceEvent, VehicleMileageLog
├── reminder_engine.py                 # compute_due_status_all, compute_due_status_for_item
├── mileage_estimator.py               # current_mileage, append_drive_estimate, drift detection
├── event_logger.py                    # log_event() — shared by CLI + Telegram + seed_loader
├── seed_loader.py                     # YAML parse + bulk import + maintenance_import_log writer
└── telegram_handlers.py               # B-099 bot conversation flows

src/server/cli/
└── maintenance.py                     # NEW — top-level CLI (subcommands)

src/server/api/sync.py                 # UPDATE — sync-back response payload extended (rides topic A)

src/pi/maintenance/                    NEW package
├── __init__.py
├── mirror_consumer.py                 # Pi-side sync-back payload upsert + write tripwire
└── parked_mode_tile.py                # Pi parked-mode reminder tile renderer

src/pi/obdii/database_schema.py        # UPDATE — add 4 SCHEMA_* constants
src/pi/obdii/sync_client.py            # UPDATE — consume 3 new sync-back payload keys
```

### Sync-back wiring (extends topic A's same payload)

```
POST /api/v1/sync
Response: {
    accepted: { ... },                              # existing
    updated_drive_summaries: [ ... ],               # topic A
    new_anomaly_log_rows: [ ... ],                  # topic A
    updated_maintenance_items: [ ... ],             # topic B NEW
    new_maintenance_events: [ ... ],                # topic B NEW
    updated_mileage_log: [ ... ]                    # topic B NEW
}
```

Single infrastructure change introduced by topic A; topic B benefits at integration time. Pi sync client consumes all 5 keys + upserts into appropriate mirror tables.

### Mileage subsystem flow

```
manual entry (CLI/Telegram)                     drive ends (Pi sync)
        │                                              │
        ▼                                              ▼
INSERT vehicle_mileage_log               US-350 trigger fires
   source='manual'                              │
   confidence='high'                            ▼
        │                              mileage_estimator.append_drive_estimate(drive_id)
        │                                       │  delta = Σ(VEHICLE_SPEED × Δt)
        │                                       │  prior = current_mileage_estimate()
        │                                       │  new = prior + delta
        │                                       ▼
        │                              INSERT vehicle_mileage_log
        │                                 source='estimated'
        │                                 mileage=new
        │                                 delta_miles_since_prior=delta
        │                                 drive_id=N
        │                                 confidence='medium'
        ▼
mileage_estimator.detect_drift()
   │  expected = current_mileage_estimate() at this moment
   │  actual = manual reading just inserted
   │  drift = actual - expected
   │  IF |drift_pct| > 5% AND days_since_last_manual >= 90:
   │      log warning
   │      surface in `status` output
   ▼
(history immutable; estimated rows never rewritten)
```

### Reminder engine — three entry points, one algorithm

Same `reminder_engine.compute_due_status_all()` powers three consumers:

| Consumer | Call site | Output format |
|---|---|---|
| CLI `status` command | Direct call → text-formatted output | Human-readable terminal output |
| Telegram proactive nudge | B-099 scheduled task calls engine → bot message | Conversational summary |
| Pi parked-mode tile | Server includes engine output in sync-back response → Pi tile renders | Tile UI (Section 6) |

One algorithm, three consumers. No duplication.

---

## 4. Reminder Engine Logic

### due_status — three primary tiers + edge tier

- **UP-TO-DATE** — not yet at the due window
- **DUE-SOON** — within criticality-scaled lead time
- **OVERDUE** — past the due date OR past the due mileage
- **NO-HISTORY** — active item with no events yet (needs history seeded)

### Lead-time thresholds (criticality-scaled)

Default DUE-SOON lead-time windows:

| Criticality | Time lead | Mileage lead | Examples |
|---|---|---|---|
| `low` | 14 days | 500 mi | air filter, wipers |
| `medium` | 30 days | 500 mi | oil change, brake fluid flush |
| `high` | 60 days | 1,000 mi | spark plugs, transmission fluid |
| `critical` | **180 days** | **5,000 mi** | timing belt — wide lead for shop scheduling + parts ordering |

Stored in `rules.yaml` (same file as topic A's `signal_weights`):

```yaml
maintenance_lead_times:
  low:      { days: 14,  miles: 500 }
  medium:   { days: 30,  miles: 500 }
  high:     { days: 60,  miles: 1000 }
  critical: { days: 180, miles: 5000 }

maintenance_drift_thresholds:
  warn_pct: 5.0
  warn_min_days: 90

maintenance_data_thinness:
  stale_mileage_days: 180
```

Spool tunes via PR + recompute (same workflow as topic A's `signal_weights`). CODEOWNERS gate requires Spool sign-off.

### Per-category interpretation

**`service_interval` items** — fire DUE-SOON if EITHER threshold within lead window:
```
next_due_date_lead  = next_due_date  - lead_days
next_due_miles_lead = next_due_miles - lead_miles

IF current_date >= next_due_date OR current_mileage >= next_due_miles:
    status = OVERDUE
ELIF current_date >= next_due_date_lead OR current_mileage >= next_due_miles_lead:
    status = DUE-SOON
ELSE:
    status = UP-TO-DATE
```

**`wear_item` items** — inspection-interval driven (mileage). Action threshold (e.g., thickness < 3mm) NOT auto-evaluated in v1; CIO eyeballs last measurement.

```
IF current_mileage >= last_event.performed_mileage + interval_miles:
    status = OVERDUE  (inspection overdue)
ELIF current_mileage >= last_event.performed_mileage + interval_miles - lead_miles:
    status = DUE-SOON
ELSE:
    status = UP-TO-DATE
```

Output shows last measurement so CIO can judge:
```
✓ Brake Pads (Front)  inspect in 2,568 mi  last: 2026-04-15 @ 86,200, thickness 7mm
```

**`regulatory` items** — time-based only:
```
IF current_date >= next_due_date:
    status = OVERDUE
ELIF current_date >= next_due_date - lead_days:
    status = DUE-SOON
ELSE:
    status = UP-TO-DATE
```

**`event_log` items** — excluded from `due_status` classification entirely (no recurring schedule = no "due" semantic). Surface only in `list-events` output by default. The `status --include-event-log` CLI flag adds them as informational rows (with `status: null`, no tier classification) for browsing alongside scheduled items. Future V0.34+ MrSpool RAG indexes them as historical context.

### Edge case handling

| Case | Behavior |
|---|---|
| `maintenance_items.active = FALSE` | Excluded from reminder engine output |
| No events for active item | `status = NO-HISTORY`; surfaced separately |
| Item has `interval_miles` but last event has `NULL performed_mileage` | Falls back to date-only; output annotates "mileage check unavailable for this item" |
| `current_mileage` data stale (>180 days since manual or estimated) | Engine logs warning; mileage-based items use date-only; output annotates "mileage data stale" |
| `current_mileage` < `last_event.performed_mileage` | Data integrity error; skip mileage check for item; refuse UP-TO-DATE claim on wrong baseline |
| Multiple events on same date (duplicate import) | Use latest by `id`; log warning if duplicate detected |
| `criticality=critical` with no events | `status = NO-HISTORY` + criticality flag (history seeding required for critical items) |
| Mileage drift >5% over 90+ days | Surface "Mileage drift X% — recalibrate" in status output |

### Sorting and display priority

`status` output ordering (highest first):

1. **OVERDUE + criticality DESC** (critical overdues top)
2. **DUE-SOON + criticality DESC**
3. **UP-TO-DATE + criticality DESC** (critical items always visible — peace of mind for timing belt)
4. **NO-HISTORY** (items missing history)

Within each tier, secondary sort by `next_due_date` ascending.

### Algorithm pseudocode

```python
def compute_due_status_all() -> List[ReminderResult]:
    items = query("SELECT * FROM maintenance_items WHERE active = TRUE")
    current_mileage_value = mileage_estimator.current_mileage()
    current_date = utcnow()
    results = []

    for item in items:
        if item.category == 'event_log':
            continue
        
        last_event = query_latest_event(item.item_id)
        if last_event is None:
            results.append(ReminderResult(item, status='NO-HISTORY'))
            continue
        
        lead = rules.maintenance_lead_times[item.criticality]
        
        date_status = classify_by_date(last_event, item, current_date, lead)
        mileage_status = classify_by_mileage(last_event, item, current_mileage_value, lead)
        
        combined = combine(date_status, mileage_status)
        
        results.append(ReminderResult(
            item=item,
            status=combined,
            next_due_date=last_event.performed_at + timedelta(days=item.interval_days),
            next_due_miles=last_event.performed_mileage + item.interval_miles if item.interval_miles else None,
            time_remaining=...,
            miles_remaining=...,
            last_event=last_event,
        ))
    
    return sort_by_priority(results)
```

Combine logic:
- Either side OVERDUE → result OVERDUE
- Either side DUE-SOON → result DUE-SOON
- Both UP-TO-DATE → UP-TO-DATE
- One side DATA-THIN + other UP-TO-DATE → UP-TO-DATE-PARTIAL

---

## 5. CLI + Telegram Surfaces + Bulk Import Format

### CLI subcommands

Entry point: `python -m server.cli.maintenance <subcommand> [args]`. Standard flags: `--json`, `--dry-run`, `--verbose`. Exit codes: 0 success / 1 validation / 2 data integrity / 3 system.

**Write subcommands:**

```bash
maintenance log
    --item <item_id>              [REQUIRED]
    --date <YYYY-MM-DD>           [REQUIRED]
    --mileage <int>               [required for service_interval w/ interval_miles]
    --cost <dollars|cents>        [accepts "35" or "3500c"]
    --performed-by <string>       [default "self"]
    --notes <string>
    --details <kv|json>           [k=v pairs or @file.json]
    --confidence <high|med|low>   [default "high"]
    --dry-run                     [validate; do not write]
    --json                        [emit written row + computed effects]

maintenance items add --item-id <slug> --category <cat> --name <str> --criticality <level> [--interval-miles N] [--interval-days N] [--notes <str>]
maintenance items deactivate --item-id <slug>
maintenance items activate --item-id <slug>

maintenance mileage log --reading <int> --date <YYYY-MM-DD|today> [--source manual|import] [--confidence high|med|low] [--notes <str>]
```

**Read subcommands:**

```bash
maintenance status [--due-soon|--overdue|--no-history] [--category <cat>] [--criticality <level>] [--include-event-log] [--json]
maintenance list-items [--category <cat>] [--active|--inactive|--all] [--json]
maintenance list-events [--item <id>] [--category <cat>] [--since <date>] [--limit N] [--json]
maintenance mileage current [--json]
maintenance mileage history [--source <s>] [--since <date>] [--limit N] [--json]
maintenance mileage drift [--since <date>] [--json]
```

**Bulk operations:**

```bash
maintenance import --file <path.yaml> [--strict|--lenient] [--dry-run] [--conflict skip|update|error] [--json]
maintenance export --file <path.yaml> [--include-events|--catalog-only] [--since <date>]
```

### Sample `status --json` output (stable contract)

```json
{
  "generated_at": "2026-05-21T16:42:00Z",
  "current_mileage": {
    "value": 87432,
    "source": "estimated",
    "confidence": "medium",
    "last_manual_date": "2026-05-15",
    "last_manual_mileage": 87100,
    "days_since_manual": 6,
    "drift_warning": null
  },
  "reminders": [
    {
      "item_id": "oil_change",
      "name": "Engine Oil + Filter",
      "category": "service_interval",
      "criticality": "medium",
      "status": "DUE-SOON",
      "last_event": {"performed_at": "2026-04-15", "performed_mileage": 86200, "id": 1234},
      "next_due_date": "2026-10-12",
      "next_due_miles": 91200,
      "time_remaining_days": 144,
      "miles_remaining": 3768,
      "trigger": "miles"
    },
    {
      "item_id": "timing_belt",
      "name": "Timing Belt + Tensioner + Water Pump",
      "category": "service_interval",
      "criticality": "critical",
      "status": "UP-TO-DATE",
      "last_event": {"performed_at": "2022-06-15", "performed_mileage": 78500, "id": 1235},
      "next_due_date": "2032-06-13",
      "next_due_miles": 168500,
      "time_remaining_days": 2214,
      "miles_remaining": 81068,
      "trigger": null
    }
  ],
  "no_history": [],
  "warnings": []
}
```

**Stable contract** consumed by: Pi parked-mode tile, Telegram bot, future MrSpool RAG (V0.34+), future web UI (V2). Breaking changes require `seed_version` bump.

### Bulk YAML import format

`seed_maintenance.yaml` — authoritative seed format; same shape for one-shot historical seed AND incremental top-up.

**File-level structure:**

```yaml
seed_version: 1
generated_at: 2026-05-21        # optional
generated_by: "Mike Cornelison"  # optional

items: [...]                     # optional
events: [...]                    # optional
mileage_log: [...]               # optional
```

All three lists optional; can import items-only, events-only, or mileage-only.

**Validation rules — items:**
- Required: `item_id`, `category`, `name`, `criticality`
- `service_interval`: at least one of `interval_miles` or `interval_days` set (typically both)
- `wear_item`: `interval_miles` should be set; `interval_days` optional
- `regulatory`: `interval_days` required; `interval_miles` must be NULL
- `event_log`: both intervals must be NULL
- `category` not in enum → error
- `criticality` not in enum → error
- `item_id` contains invalid chars (non-alphanumeric/underscore) → error

**Validation rules — events:**
- Required: `item_id`, `performed_at`
- `item_id` must exist in `maintenance_items` (in same file or pre-existing in DB; items seed first within an import pass)
- If item has `interval_miles` and event confidence is `high` → `performed_mileage` should be set (warning if missing, not error)
- `cost_cents` must be non-negative integer
- `details_json` must be valid JSON (inline YAML map auto-serialized)

**Validation rules — mileage_log:**
- Required: `recorded_at`, `mileage`, `source`
- `mileage` must be positive integer
- `source` must be in enum
- Mileage less than prior reading of same source → warning (could be valid for replaced odometer, but flag)

**Conflict resolution:**
- `items`:
  - `skip` (default with `--lenient`) — existing row untouched
  - `update` — overwrite catalog row with seed values
  - `error` (default with `--strict`) — import fails on duplicate
- `events`:
  - Default: warn but allow (multiple events on same date are valid)
  - `--conflict=error`: aborts on exact duplicate `(item_id, performed_at, performed_mileage)`
- `mileage_log`:
  - Same `(recorded_at, source)` = duplicate; default skip with warning

**Audit trail:**

Each import writes a row to `maintenance_import_log` with file path, SHA-256 hash, summary counts. Re-import of same file_hash = idempotent no-op (records attempt but writes nothing).

### Telegram conversation flows (rides B-099)

**State machine:**

```
[IDLE] ──► user trigger ──► [INTENT_PARSE]
                                │
                                ├─ "log <item>"  ─► [LOG_FLOW]
                                ├─ "status"      ─► fetch + emit + IDLE
                                ├─ "mileage"     ─► [MILEAGE_FLOW]
                                └─ unrecognized  ─► help, IDLE

[LOG_FLOW] (multi-step)
   ASK_MILEAGE → ASK_COST → ASK_NOTES → CONFIRM → commit + summary

[MILEAGE_FLOW]
   ASK_READING → commit + drift check + summary

Timeout: 5 min idle → conversation aborts; "nothing was saved"
Error recovery: 3 failed parses → bot offers escape
```

**Reactive flow example:**

```
CIO:  log oil change
Bot:  Oil change. Mileage?
CIO:  87432
Bot:  Cost? (or "skip")
CIO:  35
Bot:  Notes? (or "none")
CIO:  Mobil 1 again, M1-301A filter
Bot:  Confirm:
        • Oil change
        • 87,432 mi
        • $35
        • "Mobil 1 again, M1-301A filter"
      Save? (yes/no)
CIO:  yes
Bot:  ✓ Logged. Next oil change due 2026-11-17 or 92,432 mi.
```

**Proactive flow example (scheduled mileage nudge):**

```
Bot:  Time for an odometer reading. What's it at?
CIO:  87432
Bot:  ✓ Logged 87,432 mi on 2026-05-21.
      Estimate was 87,389; +43 mi drift over 4 days (good).
      📋 1 item due soon: Oil change in 768 mi.
```

**Reminder push (proactive at threshold crossings):**

```
Bot:  📋 Heads up — Oil Change just crossed into "due soon" 
      (5,000 mi reached; was at 86,200 last service).
      Schedule when you can. ($35 + 30 min DIY)
```

Each item-transition emits one notification per crossing. CIO can `mute oil_change` to suppress further nudges; suppression resets when next event lands.

### CLI + Telegram error mapping

| Error class | CLI behavior | Telegram behavior |
|---|---|---|
| Validation error | Exit 1; error to stderr | Bot: "That doesn't look like a valid date. Try YYYY-MM-DD or 'today'." |
| Item not in catalog | Exit 1; suggest closest match | Bot: "I don't know that item. Try one of: oil_change, brake_pads_front..." |
| Mileage less than prior | Exit 2; warns | Bot: "That mileage is lower than your last reading (87,432). Is the odometer correct?" |
| Server DB unreachable | Exit 3; retry guidance | Bot: "Server unreachable. Try again in a minute." |
| Duplicate event | Strict: error; Lenient: warn-skip | Bot: "Already logged that one — looks identical to event #1234. Skipping." |

---

## 6. Pi Parked-Mode Tile + Testing

### Pi parked-mode tile (carousel cell)

Lives in B-086 carousel as sibling to topic A's anomaly tile. Two within-tile states: SUMMARY + DETAIL.

**SUMMARY state — all up to date:**

```
┌──────────────────────────────────────────────────┐
│  MAINTENANCE                  87,432 mi (est.)   │
│                                                  │
│              ┌─────────────────────┐             │
│              │     ALL CURRENT     │             │
│              └─────────────────────┘             │
│                                                  │
│  0 overdue  •  0 due soon  •  5 up to date       │
│                                                  │
│  Next action:                                    │
│    Oil Change — in 4,568 mi / 144 days           │
│                                                  │
│  ──────────────────────────────────────          │
│  Last manual reading: 6 days ago                 │
│                                                  │
│                                    [tap detail]  │
└──────────────────────────────────────────────────┘
                  480 × 320 OSOYOO
```

**SUMMARY state — due soon:**

```
┌──────────────────────────────────────────────────┐
│  MAINTENANCE                  87,432 mi (est.)   │
│                                                  │
│              ┌──────────────┐                    │
│              │   DUE SOON   │                    │
│              └──────────────┘                    │
│                                                  │
│  0 overdue  •  2 due soon  •  3 up to date       │
│                                                  │
│  Up next:                                        │
│    ⚠ Oil Change — 768 mi / 150 d                 │
│    ⚠ Registration — 105 days                     │
│                                                  │
│                                    [tap detail]  │
└──────────────────────────────────────────────────┘
```

**SUMMARY state — overdue critical (auto-snap red flashing):**

```
┌──────────────────────────────────────────────────┐
│  MAINTENANCE — ⚠ OVERDUE      87,432 mi (est.)   │
│                                                  │
│              ┌────────────────┐                  │
│              │   ⚠ OVERDUE    │  (red flashing)  │
│              └────────────────┘                  │
│                                                  │
│  ⚠ CRITICAL OVERDUE:                             │
│     Timing Belt — 5,232 mi over / 4 mo over      │
│     INTERFERENCE ENGINE — STOP DRIVING           │
│                                                  │
│  Last replaced: 2022-06-15 @ 78,500              │
│                                                  │
│                                    [tap detail]  │
└──────────────────────────────────────────────────┘
```

`criticality=critical` items overdue → tile auto-snaps to this view on every parked-mode entry. Same auto-snap behavior as topic A's STOP-DRIVING grade. Overrides carousel last-shown state until acknowledged via DETAIL view.

**DETAIL state — full reminder list:**

```
┌──────────────────────────────────────────────────┐
│  ‹ back            MAINTENANCE — Full list       │
│                                                  │
│  ⚠ DUE SOON                                      │
│  ─────────────────────────────────────────────   │
│  Oil Change         768 mi / 150 d               │
│  Registration       105 days                     │
│                                                  │
│  ✓ UP TO DATE                                    │
│  ─────────────────────────────────────────────   │
│  Timing Belt        81,068 mi / 6+ yr   CRITICAL │
│  Brake Pads F       2,568 mi (inspect)           │
│  Mod: BOV install   one-off · 2024-03-12         │
│                                                  │
│                                       [tap back] │
└──────────────────────────────────────────────────┘
```

DETAIL view sorted by priority. Critical UP-TO-DATE items always shown last for peace-of-mind visibility.

**Refresh + staleness:**

- Tile reads Pi-local mirror (populated by sync-back per Section 3)
- Header shows mileage source: `(est.)` or `(manual)` based on `current_mileage` source
- If mileage data stale (>180 days since manual + estimated): dim mileage; "(mileage stale)" annotation
- Sync-back round-trip after engine-off refreshes; tile updates next render cycle

### Testing approach

**Unit tests:**

| Module | Coverage |
|---|---|
| `reminder_engine.py` | Per-category due_status classification (4 categories × tier transitions × edge cases). NO-HISTORY. DATA-THIN. Combine algorithm. Sort/priority ordering. |
| `mileage_estimator.py` | `current_mileage()` algorithm (manual + estimated sum). `append_drive_estimate()` from synthetic realtime_data fixtures. Drift detection at 3%, 5%, 10%. Negative drift error path. |
| `seed_loader.py` | Schema validation per row type. Required fields per category. Conflict resolution modes. Strict vs lenient. Dry-run. File hash idempotency. |
| `event_logger.py` | Required-field validation. Duplicate detection. Source tagging. FK validation against catalog. |
| `telegram_handlers.py` | State-machine transitions. Timeout abort. Error recovery (3 bad inputs → escape). |

**Integration tests (against seeded fixtures):**

Reference fixture `tests/fixtures/seed_maintenance_v1_mvp.yaml` holds 5 MVP items + seed events + initial mileage_log row.

```python
@pytest.mark.parametrize("scenario,expected_status_counts", [
    ("fresh_seed",       {"OVERDUE": 0, "DUE-SOON": 0, "UP-TO-DATE": 5}),
    ("oil_due_soon",     {"OVERDUE": 0, "DUE-SOON": 1, "UP-TO-DATE": 4}),
    ("oil_overdue",      {"OVERDUE": 1, "DUE-SOON": 0, "UP-TO-DATE": 4}),
    ("timing_belt_warn", {"OVERDUE": 0, "DUE-SOON": 1, "UP-TO-DATE": 4}),
    ("multiple_due",     {"OVERDUE": 1, "DUE-SOON": 2, "UP-TO-DATE": 2}),
])
def test_reminder_engine_against_seeded_state(scenario, expected_status_counts):
    ...
```

**Idempotency tests:**
- Re-import same YAML twice → second is no-op (`file_hash` match detected in `maintenance_import_log`)
- Re-run reminder engine → same output for same DB state
- Sync-back round-trip twice → idempotent on Pi mirror (UPSERT)

**Pi-side write tripwire test:**
```python
def test_pi_mirror_write_tripwire():
    mirror = MaintenanceItemsMirror(pi_db)
    with pytest.raises(NotImplementedError, match="forbidden"):
        mirror.insert_user_authored(...)
```

**Drive-simulator integration (rides US-355):**

Once US-355 (Sprint 41 deploy-context drive simulator) lands, maintenance integration tests run inside that harness with real Pi SQLite + server MariaDB. Mileage subsystem: synthetic drives produce expected `vehicle_mileage_log` `source='estimated'` rows. Sync-back: server-written events appear in Pi mirror tables after round-trip. Reminder engine: end-to-end (seed → events → status → Pi tile render).

Same gate as topic A. No synthetic seam mocks; deploy artifact runs.

**CLI + Telegram smoke tests:**

CLI: every subcommand under `pytest --capsys`; verifies exit codes + JSON output schemas match documented contracts.

Telegram: B-099 provides `MockBot` harness; conversation flows traced; state-machine transitions asserted.

---

## 7. V1.0 MVP Acceptance Criteria

- [ ] Four new tables created (`maintenance_items`, `maintenance_events`, `vehicle_mileage_log`, `maintenance_import_log`); server-side migration + Pi-side SCHEMA_* additions; schema parity verified
- [ ] `seed_maintenance_v1_mvp.yaml` reference fixture authored with 5 MVP items + sample events + initial mileage
- [ ] Bulk import CLI runs successfully against the reference fixture (`--strict` mode); re-running is idempotent (`file_hash` match)
- [ ] `reminder_engine.compute_due_status_all()` produces correct output for all 5 MVP items across all 5 test scenarios
- [ ] `mileage_estimator.current_mileage()` algorithm works (manual + integration); drift detection fires at 5% threshold over 90+ days
- [ ] All CLI subcommands functional: `log`, `items add/list/deactivate`, `mileage log/current/history/drift`, `status`, `list-events`, `import`, `export`
- [ ] CLI `status --json` output matches documented schema contract
- [ ] Sync-back response payload extended with 3 new keys (`updated_maintenance_items`, `new_maintenance_events`, `updated_mileage_log`); rides topic A's same `/api/v1/sync` extension
- [ ] Pi sync client consumes new payload keys + upserts into mirror tables
- [ ] Pi-side write tripwire raises `NotImplementedError` on direct write attempt (B-104 invariant)
- [ ] Pi parked-mode tile renders SUMMARY + DETAIL states; auto-snaps red flashing on critical OVERDUE
- [ ] Idempotency tests pass: re-import same YAML = no diff; re-compute reminder engine = same output
- [ ] Drift-detection test: simulated 5% drift over 90+ days surfaces warning in `status` output
- [ ] Drive-simulator integration test (rides US-355): mileage integration from synthetic drive produces correct `vehicle_mileage_log` row
- [ ] CODEOWNERS gate: `rules.yaml maintenance_*` sections require Spool sign-off (same path as topic A's Spool-rule registry)
- [ ] Documentation: `docs/maintenance-tracking-operator-guide.md` covers CLI usage, YAML format, conflict-resolution modes
- [ ] Telegram conversation flows working IF B-099 has landed; otherwise documented + acceptable to ship CLI-only in v1

---

## 8. Open Questions / Followups

1. **Web UI deferred to V2** — at what V version does it land? Depends on whether CLI + Telegram + Pi tile prove sufficient or whether typed-form entry on phone proves needed
2. **Telegram dependency on B-099** — does B-099 land before or after this work? If B-099 is delayed, this ships CLI-only and waits for B-099 to add Telegram surfaces
3. **Multi-vehicle escape hatch** — when (if ever) another vehicle enters the picture, schema migration adds `vehicle_id`; v1 hard-codes implicit single vehicle
4. **Automated measurement-threshold checks** — v1 shows wear-item measurements; v2 could auto-flag below-threshold. Useful enhancement or unnecessary?
5. **Receipt scan attachments** — `attachments_json` reserved column; v2 wires actual file storage. Useful for tax/insurance documentation
6. **Default catalog seed file** — should the project ship a `default_4g63_catalog.yaml` with all common 4G63 items pre-populated for any user, or stay project-specific? Affects whether this design could ever generalize beyond Mike's car
7. **Proactive Telegram nudge cadence** — every 30 days for mileage prompt? Quarterly? After N drives since last manual reading? Tunable via `rules.yaml` config

---

## 9. Related Backlog Items

- **B-086** GEM-1 warnings-first quiet UI — carousel pattern this tile lives in (sibling to topic A's anomaly tile)
- **B-094** GEM-9 MrSpool RAG digital twin — V0.34+ consumes maintenance state as RAG context
- **B-099** Telegram driver-context bidirectional — infrastructure dependency for conversational entry + proactive nudges
- **B-104** Server-side analytics authority — architectural foundation (server-writer, Pi-mirror pattern)
- **US-355** Sprint 41 deploy-context drive simulator — integration test gate (shared with topic A)
- **Topic A spec** `docs/superpowers/specs/2026-05-21-post-drive-anomaly-engine-design.md` — sibling design sharing sync-back wiring + Pi-mirror pattern + `rules.yaml` config file + US-355 test harness

---

## Spec Provenance

- 2026-05-21 — Brainstorm session with CIO via Spool (continuation of 2026-05-14 GEM brainstorm). Six design sections approved one-at-a-time. MVP-first vertical-slice pattern carried from topic A. Timing-belt category re-classification surfaced + corrected mid-Section-4. Spec drafted to this file.
- Source materials: prior gem brainstorm `offices/pm/inbox/2026-05-14-from-spool-display-brainstorm-gems-filtered.md`; topic A spec `docs/superpowers/specs/2026-05-21-post-drive-anomaly-engine-design.md` (shared infrastructure); Sprint 41 B-104 architectural epic; Spool knowledge.md 4G63 maintenance specifications; CIO Q&A 2026-05-14 (Q1-Q8) + 2026-05-21 brainstorm answers.
