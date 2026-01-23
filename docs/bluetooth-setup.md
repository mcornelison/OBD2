# Bluetooth OBD-II Dongle Setup Guide

## Overview

This guide covers pairing your OBD-II Bluetooth dongle with a Raspberry Pi for use with the Eclipse OBD-II Performance Monitor. The instructions use `bluetoothctl`, the standard Bluetooth command-line tool on Linux.

**Last Updated**: 2026-01-23

---

## Prerequisites

- Raspberry Pi with Bluetooth capability (built-in or USB adapter)
- OBD-II Bluetooth dongle (ELM327-compatible)
- Vehicle with OBD-II port (1996+ for US vehicles)
- Bluetooth services installed:
  ```bash
  sudo apt install bluetooth bluez bluez-tools
  ```

---

## Step 1: Find Your Dongle's MAC Address

The MAC address is a unique identifier in the format `XX:XX:XX:XX:XX:XX`. You'll need this to pair and configure the application.

### 1.1 Prepare the Dongle

1. **Turn on your vehicle's ignition** (engine doesn't need to run)
2. **Plug the OBD-II dongle** into your vehicle's OBD-II port
   - Usually located under the dashboard, near the steering column
3. **Wait for initialization** - Most dongles have an LED that blinks when ready

### 1.2 Start Scanning

On your Raspberry Pi:

```bash
bluetoothctl
```

You'll enter the bluetoothctl interactive shell:

```
Agent registered
[CHG] Controller B8:27:EB:XX:XX:XX Pairable: yes
[bluetooth]#
```

Start scanning for devices:

```
[bluetooth]# scan on
```

**Expected output:**
```
Discovery started
[CHG] Controller B8:27:EB:XX:XX:XX Discovering: yes
[NEW] Device AA:BB:CC:DD:EE:FF OBDII
[NEW] Device 11:22:33:44:55:66 ELM327
[NEW] Device 77:88:99:AA:BB:CC Vgate iCar Pro
```

### 1.3 Identify Your Dongle

Look for device names like:
- `OBDII`, `OBD2`, `OBD-II`
- `ELM327` (most common protocol chip)
- `Vgate`, `Vgate iCar`, `Vgate iCar Pro`
- `OBDLink MX+`, `OBDLink LX`
- `KONNWEI`, `BAFX`, `Veepeak`

**Note the MAC address** (e.g., `AA:BB:CC:DD:EE:FF`)

Stop scanning once found:

```
[bluetooth]# scan off
```

### 1.4 Alternative: List Known Devices

If you've previously connected to the dongle:

```bash
# Outside bluetoothctl
bluetoothctl devices
```

**Expected output:**
```
Device AA:BB:CC:DD:EE:FF OBDII
```

---

## Step 2: Pair the Dongle

Pairing establishes a trusted connection between the Raspberry Pi and the dongle.

### 2.1 Start Pairing

In the bluetoothctl shell:

```
[bluetooth]# pair AA:BB:CC:DD:EE:FF
```

Replace `AA:BB:CC:DD:EE:FF` with your dongle's MAC address.

**Expected output:**
```
Attempting to pair with AA:BB:CC:DD:EE:FF
[CHG] Device AA:BB:CC:DD:EE:FF Connected: yes
Request PIN code
[agent] Enter PIN code: 1234
[CHG] Device AA:BB:CC:DD:EE:FF Paired: yes
Pairing successful
[CHG] Device AA:BB:CC:DD:EE:FF ServicesResolved: yes
```

### 2.2 Enter PIN Code

Most OBD-II dongles use one of these default PIN codes:
- `1234` (most common)
- `0000`
- `6789`
- `1111`

If you don't know your PIN, try `1234` first - it works for ~90% of dongles.

### 2.3 Pairing Troubleshooting

If pairing fails:

```
[bluetooth]# agent on
[bluetooth]# default-agent
[bluetooth]# pair AA:BB:CC:DD:EE:FF
```

If the device times out:
```
[bluetooth]# scan on
# Wait for device to appear, then immediately:
[bluetooth]# pair AA:BB:CC:DD:EE:FF
```

---

## Step 3: Trust the Device for Auto-Reconnect

Trusting the device allows automatic reconnection without re-pairing.

```
[bluetooth]# trust AA:BB:CC:DD:EE:FF
```

**Expected output:**
```
[CHG] Device AA:BB:CC:DD:EE:FF Trusted: yes
Changing AA:BB:CC:DD:EE:FF trust succeeded
```

This is **critical** for the application to connect automatically on startup.

---

## Step 4: Verify the Pairing

### 4.1 Check Device Info

```
[bluetooth]# info AA:BB:CC:DD:EE:FF
```

**Expected output:**
```
Device AA:BB:CC:DD:EE:FF (public)
	Name: OBDII
	Alias: OBDII
	Class: 0x001f00
	Paired: yes
	Trusted: yes
	Blocked: no
	Connected: yes
	LegacyPairing: no
	UUID: Serial Port               (00001101-0000-1000-8000-00805f9b34fb)
```

**Key points to verify:**
- `Paired: yes`
- `Trusted: yes`
- `UUID: Serial Port` - This indicates SPP (Serial Port Profile) support

### 4.2 Exit bluetoothctl

```
[bluetooth]# quit
```

### 4.3 List Paired Devices

Verify the device is in your paired devices list:

```bash
bluetoothctl paired-devices
```

**Expected output:**
```
Device AA:BB:CC:DD:EE:FF OBDII
```

---

## Step 5: Verify Connection with rfcomm

`rfcomm` creates a serial port connection to the Bluetooth device.

### 5.1 Bind the Device

```bash
sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF
```

This creates `/dev/rfcomm0` which can be used like a serial port.

### 5.2 Verify the Binding

```bash
ls -l /dev/rfcomm0
```

**Expected output:**
```
crw-rw---- 1 root dialout 216, 0 Jan 23 10:30 /dev/rfcomm0
```

### 5.3 Test Connection with screen (Optional)

```bash
sudo apt install screen
screen /dev/rfcomm0
```

Type `ATZ` and press Enter. Expected response: `ELM327 v1.5` or similar.

Press `Ctrl+A` then `K` then `Y` to exit screen.

### 5.4 Release the Binding

```bash
sudo rfcomm release 0
```

---

## Step 6: Verify Connection with python-OBD

This is the most reliable verification method - it tests the actual OBD protocol.

### 6.1 Install python-OBD

```bash
pip install obd
```

### 6.2 Create Test Script

Create a file named `test_obd_connection.py`:

```python
import obd

# Connect using MAC address
connection = obd.OBD(portstr="AA:BB:CC:DD:EE:FF")

if connection.is_connected():
    print("SUCCESS: Connected to OBD-II adapter!")

    # Try to get vehicle VIN
    response = connection.query(obd.commands.VIN)
    if response.value:
        print(f"Vehicle VIN: {response.value}")

    # Try to get RPM (vehicle must be running)
    response = connection.query(obd.commands.RPM)
    if response.value:
        print(f"Engine RPM: {response.value}")
    else:
        print("Note: Start engine to read RPM")

    connection.close()
else:
    print("FAILED: Could not connect")
    print("Status:", connection.status())
```

### 6.3 Run the Test

```bash
python test_obd_connection.py
```

**Expected output (with engine running):**
```
SUCCESS: Connected to OBD-II adapter!
Vehicle VIN: 1HGBH41JXMN109186
Engine RPM: 750.0 revolutions_per_minute
```

**Expected output (engine off):**
```
SUCCESS: Connected to OBD-II adapter!
Vehicle VIN: 1HGBH41JXMN109186
Note: Start engine to read RPM
```

---

## Step 7: Configure the Application

### 7.1 Set MAC Address in .env

Edit your `.env` file:

```bash
cp .env.production.example .env
nano .env
```

Set the `OBD_BT_MAC` variable:

```bash
# OBD-II Bluetooth dongle MAC address
OBD_BT_MAC=AA:BB:CC:DD:EE:FF
```

Replace `AA:BB:CC:DD:EE:FF` with your actual MAC address.

### 7.2 Verify Hardware Configuration

Run the hardware verification script:

```bash
python scripts/verify_hardware.py --mac AA:BB:CC:DD:EE:FF
```

**Expected output:**
```
============================================================
  Eclipse OBD-II Hardware Verification
============================================================

============================================================
  Python Version Check
============================================================
  [PASS] Python 3.11 (CRITICAL)
         Required: >= 3.11

============================================================
  Bluetooth Adapter Check
============================================================
  [PASS] Bluetooth service
         systemctl status bluetooth
  [PASS] Bluetooth adapter (hci0)
         UP and RUNNING

============================================================
  OBD-II Dongle Check
============================================================
  [PASS] OBD-II dongle (AA:BB:CC:DD:EE:FF)
         Found in paired devices

============================================================
  Summary
============================================================
  Total checks: 6
  Passed: 6

  All checks passed! Hardware is ready.
```

---

## Common Troubleshooting

### Dongle Not Appearing in Scan

**Problem:** Device doesn't appear when scanning.

**Solutions:**
1. Ensure vehicle ignition is ON
2. Unplug and replug the dongle
3. Wait 10-15 seconds for dongle to initialize
4. Move Pi closer to the vehicle
5. Check if dongle LED is blinking (indicates active)

```bash
# Reset Bluetooth adapter
sudo hciconfig hci0 down
sudo hciconfig hci0 up
sudo systemctl restart bluetooth
```

### Pairing Fails

**Problem:** `Pairing failed - authentication failed` or `org.bluez.Error.AuthenticationFailed`

**Solutions:**
1. Try different PIN codes: `1234`, `0000`, `6789`
2. Remove existing pairing and retry:
   ```
   [bluetooth]# remove AA:BB:CC:DD:EE:FF
   [bluetooth]# pair AA:BB:CC:DD:EE:FF
   ```
3. Power cycle the dongle (unplug for 10 seconds)

### Connection Drops

**Problem:** Connection works initially but drops after a few seconds.

**Solutions:**
1. Ensure device is trusted:
   ```
   [bluetooth]# trust AA:BB:CC:DD:EE:FF
   ```
2. Check for interference (WiFi, other Bluetooth devices)
3. Ensure adequate power to Bluetooth adapter

### Cannot Create rfcomm Device

**Problem:** `rfcomm: Can't create device`

**Solutions:**
1. Ensure rfcomm module is loaded:
   ```bash
   sudo modprobe rfcomm
   ```
2. Add to `/etc/modules`:
   ```bash
   echo "rfcomm" | sudo tee -a /etc/modules
   ```
3. Check if serial port profile is supported:
   ```
   [bluetooth]# info AA:BB:CC:DD:EE:FF
   ```
   Look for `UUID: Serial Port`

### python-OBD Connection Fails

**Problem:** `obd.OBD()` returns disconnected status.

**Solutions:**
1. Use Bluetooth MAC address, not rfcomm device:
   ```python
   # Good
   connection = obd.OBD(portstr="AA:BB:CC:DD:EE:FF")

   # Also works
   connection = obd.OBD(portstr="/dev/rfcomm0")
   ```
2. Ensure no other program is using the connection
3. Check if dongle is paired and trusted

### Permission Denied

**Problem:** `Permission denied` when accessing Bluetooth or rfcomm.

**Solutions:**
1. Add user to `dialout` and `bluetooth` groups:
   ```bash
   sudo usermod -a -G dialout,bluetooth $USER
   # Log out and back in for changes to take effect
   ```
2. Or run with sudo (not recommended for production)

### Bluetooth Service Not Running

**Problem:** `Failed to connect: org.freedesktop.DBus.Error.NoReply`

**Solution:**
```bash
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
sudo systemctl status bluetooth
```

---

## Quick Reference Commands

```bash
# Start bluetoothctl
bluetoothctl

# Scan for devices
scan on
scan off

# Pair and trust a device
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF

# Check device status
info AA:BB:CC:DD:EE:FF

# List paired devices
paired-devices

# Remove a device
remove AA:BB:CC:DD:EE:FF

# Exit bluetoothctl
quit

# Check Bluetooth service
sudo systemctl status bluetooth

# Restart Bluetooth
sudo systemctl restart bluetooth

# Create rfcomm device
sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF

# Release rfcomm device
sudo rfcomm release 0

# Check rfcomm status
rfcomm show
```

---

## Related Documentation

- [Deployment Checklist](deployment-checklist.md) - Full deployment guide
- [Testing Guide](testing.md) - Testing procedures including simulator mode
- [Production Environment Template](../.env.production.example) - Environment configuration

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-23 | Claude | Initial Bluetooth setup documentation (US-OSC-019) |
