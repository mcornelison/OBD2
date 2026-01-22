# OBD2 Patterns & Requirements Document

**Source:** Analysis of prior OBD2 project (Z:\O\OBD2)
**Date:** 2026-01-22
**Purpose:** Capture reusable patterns, lessons learned, and requirements for OBD2v2

---

## 1. Database Requirements

### 1.1 Schema Design: Two-Table Architecture

**Requirement:** Separate static vehicle data from streaming telemetry data.

| Table | Purpose | Cardinality |
|-------|---------|-------------|
| `OBD2StaticData` | Vehicle identification (VIN, make, model, year) | One record per vehicle |
| `OBD2StreamingData` | Time-series sensor readings | Many records per vehicle |

**Static Data Fields:**
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `vin` (TEXT UNIQUE) - Vehicle Identification Number
- `calibration_id`, `ecu_name`, `fuel_type` - ECU metadata
- `engine_displacement` (REAL)
- `make`, `model`, `year`, `body_class` - Vehicle info
- `engine_cylinders`, `engine_hp`, `plant_country` - Specs

**Streaming Data Fields:**
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `static_data_id` (INTEGER FK → OBD2StaticData.id)
- `timestamp` (TEXT) - ISO 8601 format
- 33+ sensor columns (rpm, speed, coolant_temp, throttle_pos, etc.)
- `dtc_codes` (TEXT) - Diagnostic trouble codes

### 1.2 Anomaly Tracking Table

**Requirement:** Track out-of-range sensor values for diagnostics.

**Fields:**
- `id`, `static_data_id` (FK), `timestamp`
- `variable` (TEXT) - Which sensor triggered anomaly
- `value` (REAL) - Actual recorded value
- `description` (TEXT) - Human-readable explanation

### 1.3 SQL Best Practices

| Practice | Example |
|----------|---------|
| Parameterized queries | `cursor.execute("SELECT * FROM t WHERE vin=?", (vin,))` |
| ISO timestamps | `datetime.now().isoformat()` |
| Foreign key relationships | `FOREIGN KEY(static_data_id) REFERENCES OBD2StaticData(id)` |
| Single commit per batch | Insert all anomalies, then `conn.commit()` once |

---

## 2. Configuration Requirements

### 2.1 Three-Level Configuration Strategy

| Level | File | Purpose |
|-------|------|---------|
| 1 | `config.json` | Application settings (non-secret) |
| 2 | `.env` | Secrets only (API keys, passwords) |
| 3 | `anomaly_thresholds.json` | Domain-specific thresholds |

### 2.2 Config File Structure

```json
{
    "bt_address": "00:1D:A5:68:98:8B",
    "obd2": {
        "static_table": "OBD2StaticData",
        "streaming_table": "OBD2StreamingData"
    },
    "database": {
        "type": "sqlite",
        "path": "./sql/obd2_data.db",
        "timeout": 30,
        "is_local": true
    },
    "streaming": {
        "interval_hz": 1,
        "end_time": null
    },
    "vin_decoder": {
        "api_url": "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json",
        "api_key": null
    }
}
```

### 2.3 Anomaly Thresholds Structure

```json
{
    "rpm": {"min": 0, "max": 7000},
    "speed": {"min": 0, "max": 200},
    "coolant_temp": {"min": -40, "max": 120},
    "battery_voltage": {"min": 11, "max": 15}
}
```

### 2.4 Config Loader Requirements

**Must support:**
- Simple access: `config.get("key", default)`
- Nested access: `config.get_nested("database", "path", default="...")`
- Environment variable resolution: `${ENV_VAR}` syntax

---

## 3. Data Model Requirements

### 3.1 Use Dataclasses for Schema Objects

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class OBD2StaticData:
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[str] = None
    # ... all fields Optional with None default
```

**Benefits:**
- Automatic `__init__`, `__repr__`, `__eq__`
- Type hints for IDE support
- Optional fields handle missing sensor data
- Field introspection: `obj.__dataclass_fields__.keys()`

### 3.2 Dynamic SQL Generation

**Requirement:** Generate INSERT statements from dataclass fields automatically.

```python
fields = list(streaming_data.__dataclass_fields__.keys()) + ["timestamp"]
values = [getattr(streaming_data, f) for f in fields[:-1]] + [now.isoformat()]
placeholders = ','.join(['?'] * len(fields))
sql = f"INSERT INTO {table} ({','.join(fields)}) VALUES ({placeholders})"
```

---

## 4. OBD2-Specific Requirements

### 4.1 Sensor Reading Pattern

**Requirement:** Each query must check success before use.

```python
result = connection.query(obd.commands.RPM)
rpm = int(result.value.magnitude) if result.is_successful() else None
```

**Key Points:**
- OBD2 queries return `Pint.Quantity` objects
- Extract `.magnitude` for numeric value
- Convert to native types (`int`, `float`)
- Return `None` for failed readings

### 4.2 VIN Caching Strategy

**Requirement:** Avoid redundant VIN decoder API calls.

1. Query VIN from vehicle
2. Check if VIN exists in `OBD2StaticData` table
3. If found: use cached data
4. If not found: call VIN decoder API, store result

### 4.3 Anomaly Detection Logic

**Requirement:** Check each sensor against configurable thresholds.

```python
for field, limits in thresholds.items():
    value = getattr(streaming_data, field, None)
    if value is not None:
        if value < limits.get("min") or value > limits.get("max"):
            # Record anomaly
```

---

## 5. Architecture Requirements


### 5.2 Dependency Injection

**Requirement:** Pass dependencies via constructor.

```python
controller = OBD2Controller(
    connection=OBD2Connection(bt_address),
    model=model,
    view=view,
    anomaly_controller=AnomalyController(anomaly_model)
)
```

### 5.3 Streaming Loop Pattern

**Requirements:**
- Configurable sampling rate (`interval_hz`)
- Optional end time for timed runs
- Graceful keyboard interrupt handling (Ctrl+C)
- Cleanup in `finally` block (close connections)

```python
try:
    while True:
        if end_time_reached:
            break
        data = read_sensors()
        detect_anomalies(data)
        save_to_database(data)
        time.sleep(interval)
except KeyboardInterrupt:
    print("Stopped by user")
finally:
    connection.close()
    database.close()
```

---

## 6. Error Handling Requirements

### 6.1 Graceful Degradation

**Requirement:** Missing sensor data should not crash the system.

- Return `None` for failed sensor queries
- Skip `None` values in anomaly detection
- Use `Optional[Type]` in dataclasses

### 6.2 External API Error Handling

**Requirement:** VIN decoder failures should not halt operation.

```python
try:
    response = requests.get(vin_api_url)
    if response.status_code == 200:
        # Process response
except Exception as e:
    print(f"VIN decode failed: {e}")
    # Continue with None values
```

### 6.3 Database Error Handling

**Requirement:** Log and continue on non-critical DB errors.

```python
try:
    cursor.execute(sql, values)
    conn.commit()
except Exception as e:
    print(f"DB operation failed: {e}")
```

---

## 7. Utility Requirements

### 7.1 Connectivity Checks

**Internet Check:**
```python
def is_internet_connected(host="8.8.8.8", port=53, timeout=3):
    # Socket connection to DNS server
```

**Bluetooth Check (Windows):**
```python
def is_bluetooth_on():
    # PowerShell: (Get-Service -Name bthserv).Status
```

### 7.2 Timestamp Handling

**Requirement:** Use ISO 8601 format for all timestamps.

```python
timestamp = datetime.now().isoformat()
# "2026-01-22T14:30:45.123456"
```

---

## 8. Lessons Learned / Anti-Patterns to Avoid

| Anti-Pattern | Correct Approach |
|--------------|------------------|
| SQL string concatenation | Parameterized queries with `?` |
| Hardcoded field lists | Dynamic generation from dataclass |
| Silent failures everywhere | Log errors, fail fast on critical paths |
| Missing cleanup | Always use `finally` for connections |
| Redundant API calls | Cache VIN data in database |
| Magic numbers | Use config file or named constants |
| Tight coupling | Dependency injection |

---

## 9. Sensor Field Reference

### Standard OBD2 PIDs (Partial List)

| Field | Type | Unit | Typical Range |
|-------|------|------|---------------|
| `rpm` | int | RPM | 0-7000 |
| `speed` | int | km/h | 0-200 |
| `coolant_temp` | float | °C | -40 to 120 |
| `throttle_pos` | float | % | 0-100 |
| `engine_load` | float | % | 0-100 |
| `intake_temp` | float | °C | -40 to 215 |
| `maf` | float | g/s | 0-655 |
| `fuel_pressure` | float | kPa | 0-765 |
| `timing_advance` | float | ° | -64 to 64 |
| `battery_voltage` | float | V | 11-15 |
| `fuel_level` | float | % | 0-100 |
| `barometric_pressure` | float | kPa | 0-255 |
| `dtc_codes` | str | - | Comma-separated |

---

## 10. Implementation Checklist

- [ ] Database schema with static/streaming separation
- [ ] Anomaly tracking table
- [ ] Config loader with nested access support
- [ ] Dataclass-based data models
- [ ] VIN caching mechanism
- [ ] Anomaly detection with configurable thresholds
- [ ] Streaming loop with graceful shutdown
- [ ] Error handling for sensors, API, database
- [ ] Connectivity utilities
- [ ] ISO timestamp formatting
- [ ] Parameterized SQL queries throughout
