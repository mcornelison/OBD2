# src/pi/ — Raspberry Pi Tier

Deployed to `chi-eclipse-tuner` only. Contains all hardware-interfacing and
real-time data collection code.

## Structure

- **`main.py`** — Entry point. Boots the orchestrator.
- **`obd_config.json`** — Pi configuration (moves to repo root in sweep 4)
- **`obd/`** — OBD-II subsystem (connection, parameters, data logging, drive detection, orchestrator, simulator, shutdown, VIN decoder, vehicle data, services)
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
