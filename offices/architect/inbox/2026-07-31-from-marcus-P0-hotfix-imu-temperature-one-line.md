from=Marcus(PM); to=Atlas(Architect); date=2026-07-31; topic=P0 one-line hotfix (CIO-directed) -- IMU reader crashes on dev.temperature, blocks states/imu; audience=agent; urgency=high; refs=US-500,US-478,US-497,sensor_reader.py:322

# P0 hotfix (CIO-directed): sensor_reader.py:322 -- guard the .temperature read

The V0.29.20 on-Pi bench validation caught this (A-16): with the genuine ICM-20948 @0x69 + `imu.enabled=true`, **every** poll fails and `states/imu` is never written → the IMU card (US-497) renders nothing. Root cause is one line.

**File:** `src/pi/sensors/sensor_reader.py`
**Line 322 (in `pollOnce`, after accel/gyro/mag on 319-321):**
```python
temp = float(dev.temperature)     # <- throws: 'ICM20948' object has no attribute 'temperature'
```
The genuine `adafruit_icm20x.ICM20948` doesn't expose `.temperature`, so this raises **before** the accel/gyro/mag sample (the fields `states/imu` actually needs) is published.

**Fix (graceful, temperature is NOT in the states/imu derived contract):**
```python
try:
    temp = float(dev.temperature)
except (AttributeError, Exception):
    temp = None
```
(or `temp = float(dev.temperature) if hasattr(dev, "temperature") else None`). Then confirm the downstream publish path accepts `temp=None` (raw EDR `temp_c` → null-when-unavailable, never fabricated) — if it doesn't, that's the second half of the one-line fix.

**Verify on the Pi (I'll redeploy after your patch):** `states/imu` present with live accel/gyro/mag; no `imu read failed` warnings; US-497 card renders g-force/compass off the real board. That retires the US-478/497 deferred on-Pi validation + closes US-500.

CIO directed a hotfix (not a sprint) — same out-of-sprint path as your A-17 capture fix. Commit to `dev`; I bump the patch version + redeploy over the wired `.9` + re-validate. Thanks.

— Marcus
