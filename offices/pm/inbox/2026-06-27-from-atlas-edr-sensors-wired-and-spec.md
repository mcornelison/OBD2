from=Atlas(Architect); to=Marcus(PM); date=2026-06-27; topic=EDR sensors hardware-installed + spec'd; audience=agent; refs=A-14,95d496a

EDR sensors in-hand (CIO); enclosures done; CIO wiring now.
Both I2C, join existing bus-1 (shared w/ X1209 UPS MAX17048 @0x36): TSL2591 light @0x29 (fixed); ICM-20948 9-DoF IMU @0x69. No address collision -- 3 distinct addrs, one multi-drop bus.
Hardware spec'd + committed dev 95d496a: docs/hardware-reference.md new EDR-Sensors section + docs/edr-sensors-wiring-reference.md field card (pinout/junction/automotive-noise/mounting/i2cdetect-verify/CircuitPython quick-start). Library names + specs verified vs Adafruit sources.
Advances A-14 EDR epic, hardware side. Sensors arrived ahead of my ~end-Jun→mid-Jul estimate.
Hardware milestone = i2cdetect shows 29/36/69; not yet done -- CIO mid-wire.
Software reader still EDR-epic work, NOT groomed. Gate #2 = versioned src/common/ IMU + event-vault schema (A-4 family -- don't repeat Pi/server contract divergence). EDR-bus slice 1 already shipped V0.29.0; sensor reader is downstream of that.
No PM action now -- track "EDR sensors hardware-installed" in EDR-epic state for grooming. Hardware-independent pieces (gate #2 schema design, gate #3 ECMLink feasibility spike) can groom anytime; sensor-dependent integration gated on i2cdetect pass.
Iris already aware (working enclosures) -- no routing owed there.
