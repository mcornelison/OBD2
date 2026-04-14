# Sweep 4 Key Classification

Source file: `src/pi/obd_config.json` (21 top-level keys).

## Top-level (shared across tiers)

- `logging` — both tiers need logger config; shape is identical so it lives shared
- `protocolVersion` — **NEW** in sweep 4; locked at `"1.0.0"` — Pi↔Server handshake
- `schemaVersion` — **NEW** in sweep 4; locked at `"1.0.0"` — DB schema version
- `deviceId` — **NEW** in sweep 4; sourced from `${DEVICE_ID}` env var

## `pi:` section (edge/collect tier)

| Key | Why Pi |
|---|---|
| `application` | Pi app metadata (name/version/environment) |
| `database` | Pi-side SQLite (path, WAL, vacuum) |
| `bluetooth` | OBDLink LX dongle — Pi-only |
| `vinDecoder` | NHTSA lookup for Pi-stored VIN |
| `display` | HDMI/GPIO display — Pi-only |
| `autoStart` | systemd-style restart on Pi |
| `staticData` | PIDs queried once on connection — Pi OBD poller |
| `realtimeData` | Pi realtime polling parameters + interval |
| `analysis` | Pi-side realtime drive-end statistics (window/outlier/triggers) — consumed by `src/pi/analysis/engine.py` |
| `profiles` | Active tuning profile + available profiles — Pi profile manager |
| `calibration` | Calibration session mode — Pi-only |
| `pollingTiers` | 4-tier polling cadence — Pi OBD poller |
| `tieredThresholds` | **Spool-authoritative** alert thresholds — Pi AlertManager reads at runtime |
| `alerts` | Alert sink config (audio/visual/log, cooldown) — Pi-side |
| `dataRetention` | Pi SQLite cleanup schedule |
| `batteryMonitoring` | Pi ADC battery voltage reader |
| `powerMonitoring` | Pi GPIO ignition-sense |
| `export` | Pi-side drive log export format/dir |
| `simulator` | Pi simulator mode for testing without ECU |

## `server:` section (analysis tier)

| Key | Source | Why Server |
|---|---|---|
| `ai` | Renamed from `aiAnalysis` | Ollama/analysis runs on Chi-Srv-01, not Pi. Rename aligns with `src/server/ai/` package name. |
| `database` | **NEW** placeholder `{}` | Future MariaDB (host/port/creds) on Chi-Srv-01 |
| `api` | **NEW** placeholder `{}` | Future FastAPI ingest endpoint on Chi-Srv-01 |

## Spool-authoritative preservation

`tieredThresholds` contains six sections (`batteryVoltage`, `coolantTemp`, `iat`, `rpm`, `stft`, `timingAdvance`) with the locked Spool values. In the new shape it lives at `pi.tieredThresholds` and must be pasted **byte-for-byte** identical. Verified at task 1 (snapshot) and task 10 (final diff).

## Non-questions (explicitly decided by plan)

- **Q**: Is `aiAnalysis` Pi or server? → **Server.** The Ollama host URL is remote; the caller is `src/server/ai/`. Renamed to `ai` under `server:`.
- **Q**: Is `analysis` (separate from `aiAnalysis`) Pi or server? → **Pi.** It drives `src/pi/analysis/engine.py`; `src/server/analysis/` is an empty skeleton.
- **Q**: Is `logging` duplicated per tier or shared? → **Shared top-level.** Shape is identical across tiers; leave it flat.

## Count check

- top-level shared: 4 (`logging` + 3 new)
- `pi:` sections: 19
- `server:` sections: 3 (1 moved + 2 new placeholders)
- Total sections in new config.json: **26**
