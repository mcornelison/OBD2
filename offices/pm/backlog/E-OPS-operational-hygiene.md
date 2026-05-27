---
id: E-OPS
status: active
createdAt: 2026-05-27
---

# E-OPS — Operational Hygiene

## Description
Standing catch-all Epic for bugs, tech debt, housekeeping, refactors, documentation
fixes, and small operational items that don't naturally fit a domain Epic
(E-001/2/3/4/5). Typed Stories filed here use type=issue / blocker / tech-debt /
housekeeping / research / security via PM Rule 11.

## Features
38 features (most complete, audit trail kept):

Documentation + standards housekeeping (8 features, mostly complete):
F-005 review untracked docs, F-009 fix error classification docs, F-011 OBD2
patterns reference, F-017 coding rules, F-018 specs-to-code drift fix,
F-019 split oversized files, F-040 6-sweep structural reorg, F-105 architecture.md
mod-history backfill (pending).

Bug fixes + hotfixes (5 features): F-020 config drift fix, F-034 battery voltage
boundary ambiguity, F-049 drive-detect idle-poll gap, F-058 connection_log noise,
F-079 sync_history timezone mismatch.

Test/build infrastructure (3 features): F-001 test-runner cleanup, F-026 simulate
DB validation test, F-038 sprint_lint script.

Hardware/probe research (5 features pending): F-048 MAX17048 calibration,
F-054 automated battery test on boot, F-066 B-047 self-update IRL drill,
F-084 preflight PID probe, F-085 BNO055 IMU sensor.

Power/UPS subsystem (5 features): F-050 powermonitor write activation,
F-051 ups slow-drain debounce, F-060 wire ups-monitor SoC, F-061 drop legacy SoC
columns, F-062 drain-event close targeted fix, F-098 in-car-vs-wall mode badge.

Drive/analytics edge cases (4 features pending): F-036 (already moved to E-002
in error — reassign during groomingnotes), F-077 connection_log idle chattiness,
F-081 ELM ATRV proxy, F-099 Telegram driver context bidirectional.

Misc + declined (4 features): F-004 commented dependencies, F-006 (declined)
camelCase → snake_case migration, F-021 push unpushed commits, F-024 remove
local Ollama refs, F-042 src/pi/obd→obdii rename, F-108 ECU lineage tracking,
F-109 Mode 02 freeze-frame.

## Context / rationale
Per spec §8, items not fitting a domain Feature home land under E-OPS. The auto-
assigned Epic parents from migration are best-guesses; refinement happens when
items are pulled into PRDs. The 35-or-so completed entries here are legacy work
products preserved in backlog.json for audit (their MD bodies live elsewhere or
are pre-existing placeholders).
