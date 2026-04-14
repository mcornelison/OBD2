# src/pi/ — Raspberry Pi Tier

Deployed to `chi-eclipse-tuner` only. Contains all hardware-interfacing and
real-time data collection code.

## Structure

- **`main.py`** — Entry point. Boots the orchestrator. Config loaded from repo-root `config.json` (see sweep 4).
- **`obd/`** — OBD-II subsystem. Connection, parameters, data logging, drive detection, orchestrator (9-module mixin package per Sweep 5 / TD-003), simulator, shutdown, VIN decoder, vehicle data, services. See `src/pi/obd/README.md` for the subpackage map.
- **`hardware/`** — GPIO, I2C, platform utilities, hardware manager
- **`display/`** — Display manager, drivers (headless, developer, minimal), adapters (Adafruit)
- **`power/`** — Battery and power monitoring
- **`alert/`** — Real-time alert manager (tiered threshold system only)
- **`profile/`** — Driving profile manager and switcher
- **`calibration/`** — Calibration session management and comparison
- **`backup/`** — Backup manager (Google Drive)
- **`analysis/`** — Pi-side realtime analysis (engine, profile statistics, helpers). Pure math is in `src/common/analysis/`.
- **`clients/`** — HTTP clients for server communication (Ollama, uploader). Skeletons — real implementations land with B-023/B-027.
- **`inbox/`** — Recommendation review inbox reader. Skeleton.

## Dependencies

- Imports from `src.common.*` allowed
- Imports from `src.server.*` **forbidden** (structurally enforced by deployment)
