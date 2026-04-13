"""
Raspberry Pi tier package.

Contains modules deployed to the in-car Raspberry Pi only:
- Hardware interfaces (GPIO, I2C, Bluetooth)
- Display drivers
- OBD-II data collection
- Real-time alerting
- Local analysis for display
- Drive detection and profile management

Not deployed to the server (Chi-Srv-01). Imports from `src.common` are allowed;
imports from `src.server` are forbidden (enforced structurally — `src.server`
won't exist on the deployed Pi).
"""
