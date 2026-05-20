---
name: Pi collector service state (as of 2026-04-20 Session 6)
description: eclipse-obd.service EXISTS and auto-starts on Pi. Currently in --simulate mode per deploy config. CIO directive 2026-04-20 to flip to real-OBD mode and archive sim infrastructure. Story 1 hotfix proposed to Marcus.
type: project
originSessionId: 71674938-eb49-443e-8781-7c8a5ea16575
---
**Fact (corrected from earlier in session)**: `eclipse-obd.service` DOES exist on the Pi at `/etc/systemd/system/eclipse-obd.service`. It is enabled, auto-starts on boot, currently running. My earlier claim that "no collector service exists" was wrong — I was grepping for `obd-collector.service` but the actual name is `eclipse-obd.service`.

**Current configuration (as of 2026-04-20 / Session 6)**:
```
ExecStart=/home/mcornelison/obd2-venv/bin/python src/pi/main.py --simulate
Restart=on-failure
RestartSec=10
```

Problems:
1. `--simulate` flag = collector reads the physics simulator, NOT `/dev/rfcomm0`. Explains why today's thermostat drill captured zero real rows, and why Ralph's earlier halt-note counted 352K synthetic rows.
2. `Restart=on-failure` (not `always`) = clean exits don't trigger restart. Insufficient for BT-flap resilience.
3. No internal BT reconnect loop in the Python code.

**CIO directive (2026-04-20 Session 6)**: *"Stop all simulated tests. We have a working system and can run real data whenever we need to. Simulations can be archived."*

**Resolution in flight** — three stories proposed to Marcus in `offices/pm/inbox/2026-04-20-from-spool-session6-findings-and-directives.md`:
- **Story 1 (S)**: Drop `--simulate` from ExecStart + `Restart=always` + enable persistent journald
- **Story 2 (M)**: Add BT reconnect loop in Python (depends on Story 1)
- **Story 3 (L, deferred)**: Power-down orchestrator (depends on audit of existing power-mgmt code — see `reference_pi_power_mgmt_codebase.md`)

**How to apply**: Future work in this area should assume the service-lifecycle foundation exists. Don't re-propose "package as systemd service" work. Focus story proposals on behavioral gaps (BT resilience, power-loss handling, simulate-mode removal) rather than packaging.

**Decay**: this memory expires when Story 1 ships (collector runs real OBD, not simulate). At that point, update to reflect the new baseline.
