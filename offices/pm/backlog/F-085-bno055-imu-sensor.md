---
id: F-085
parent: E-OPS
status: pending
renamedFrom: B-085
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-085: BNO055 9-DOF IMU sensor for G-force / acceleration / vehicle attitude

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (P2 — Ralph recommendation: MEDIUM for V0.28.x or V0.29.0)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | L (1 sprint)        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Add a fundamentally new signal class our project does not have today: lateral G's during cornering, longitudinal G's for 0-60 / hard-braking, vehicle attitude (pitch/roll/yaw). Highly relevant for a turbocharged performance car.

**Tuning-grade applications:**
- 0-60 measurement (longitudinal G integrated over time)
- Lateral G correlated with fuel-trim swing during cornering (catches fuel-pickup issues)
- Brake-G events as thermal-warning trigger
- Launch-G correlation with timing-pull events (catches knock-on-launch)

**Hardware:** Adafruit BNO055 ~$25, I2C bus (already have I2C for MAX17048 + display). Same i2c_client pattern.

**Scope:** hardware install (1 day) + new `imu_sensor.py` reader + new `imu_data` table + Pi-to-server sync + Spool prompt updates.

**Source:** Ralph (Rex) PM note 2026-05-14 — research dive into `brian03079/piObdDashboard` repo. Approved by CIO for backlog entry.

**Dependencies:** Adafruit BNO055 library; physical hardware purchase + install.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
