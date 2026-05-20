# Summer 2026 Upgrade Plan

> Vehicle plan tracked by Spool. Migrated 2026-05-18 from `~/.claude/.../project_summer2026_upgrade.md` per CIO directive.

Summer 2026: Full E85 conversion with ECMLink V3, wideband, injectors, and exhaust.

**Why:** CIO wants the car properly tuned on E85 with real monitoring — more power, better knock resistance, cooler combustion. The Pi 5 + Chi-Srv-01 system provides real-time monitoring (Pi) and post-drive AI analysis (server).

**How to apply:**
- All tuning specs flow through Spool → PM → story review → sprint → developer
- 8-step install order is locked (safety gates, no E85 until Step 8)
- Illinois emissions: high-flow catted only, no catless, keep stock exhaust as fallback
- System has two data phases: Phase 1 (OBD-II, ~5 PIDs/sec) and Phase 2 (ECMLink, 50+ params at 10-50 Hz)
- Comprehensive tuning spec delivered to PM inbox 2026-04-10 — PM needs to process it
- `/review-stories-tuner` skill created for pre-sprint quality gate
