# Hardware Reference Documentation

## Overview

This document provides complete hardware specifications for the Eclipse OBD-II Raspberry Pi system. It covers the target platform, UPS HAT, display, and all hardware interfaces.

**Last Updated**: 2026-01-25

For detailed specifications and developer guidance, see [specs/samples/piSpecs.md](../specs/samples/piSpecs.md).

---

## Target Platform

### Raspberry Pi 5 (8GB)

| Specification | Value |
|---------------|-------|
| Model | Raspberry Pi 5 Model B |
| RAM | 8GB LPDDR4X |
| CPU | Broadcom BCM2712, Quad-core Cortex-A76 @ 2.4GHz |
| Architecture | ARM64 (aarch64) |
| Operating System | Raspberry Pi OS (64-bit, Bookworm) |
| Storage | 128GB A2 U3/V30 microSD (high-endurance recommended) |
| Power Input | USB-C, 5V/5A (27W) |

### Key Interfaces

| Interface | Purpose |
|-----------|---------|
| USB-C | Power input from X1209 UPS HAT |
| GPIO | Shutdown button, status LED |
| I2C | UPS telemetry (battery voltage, current, percentage) |
| HDMI | Display output (OSOYOO 3.5" screen) |
| USB-A | Touch input from display |
| Bluetooth | OBD-II ELM327 dongle communication |

---

## UPS HAT: Geekworm X1209

The X1209 provides uninterruptible power for safe shutdown when car ignition is turned off.

### Specifications

| Specification | Value |
|---------------|-------|
| Model | Geekworm X1209 V1.0 |
| Input Voltage | 5V via USB-C (car adapter or wall power) |
| Output Voltage | 5.1V @ 5A (USB-C to Pi) |
| Battery Type | Single 18650 Li-ion cell (protected) |
| Battery Capacity | 2600-3500mAh typical |
| Charging Current | Up to 2A |
| Protection | Over-charge, over-discharge, short-circuit |
| Communication | I2C for telemetry |

### Features

- **Auto-switchover**: Seamlessly switches to battery when external power is lost
- **Auto power-on**: Automatically powers Pi when external power is restored
- **Safe shutdown**: Provides I2C telemetry for software-controlled graceful shutdown
- **Battery protection**: Built-in protection circuit prevents battery damage

---

## I2C Configuration

### Bus and Address

| Parameter | Value | Notes |
|-----------|-------|-------|
| I2C Bus | 1 | Default on Raspberry Pi (`/dev/i2c-1`) |
| UPS Address | `0x36` | Primary address for X1209 |
| Alternate Address | `0x57` | Some X1209 variants use this |

### Enabling I2C

```bash
# Enable I2C via raspi-config (non-interactive)
sudo raspi-config nonint do_i2c 0

# Verify I2C is enabled
ls /dev/i2c-*
# Expected output: /dev/i2c-1

# Install I2C tools
sudo apt install -y i2c-tools

# Scan for devices (should show 0x36 or 0x57)
sudo i2cdetect -y 1
```

### Telemetry Data Points

The X1209 exposes the following telemetry via I2C:

| Register | Data | Type | Unit | Notes |
|----------|------|------|------|-------|
| 0x02-0x03 | Battery Voltage | 16-bit | mV | Read as word, divide by 1000 for volts |
| 0x04-0x05 | Battery Current | 16-bit signed | mA | Positive = charging, Negative = discharging |
| 0x06 | Battery Percentage | 8-bit | % | 0-100, estimated state of charge |
| 0x08 | Power Source | 8-bit | enum | 0 = external, 1 = battery |

### Reading Telemetry (Python Example)

```python
import smbus2

I2C_BUS = 1
UPS_ADDRESS = 0x36

bus = smbus2.SMBus(I2C_BUS)

# Read battery voltage (mV as 16-bit word)
voltage_mv = bus.read_word_data(UPS_ADDRESS, 0x02)
voltage_v = voltage_mv / 1000.0

# Read battery current (mA as signed 16-bit)
current_raw = bus.read_word_data(UPS_ADDRESS, 0x04)
if current_raw > 32767:
    current_raw -= 65536  # Convert to signed
current_ma = current_raw

# Read battery percentage
percentage = bus.read_byte_data(UPS_ADDRESS, 0x06)

# Read power source (0=external, 1=battery)
power_source = bus.read_byte_data(UPS_ADDRESS, 0x08)
```

---

## GPIO Pin Assignments

### Pin Configuration

| GPIO Pin | BCM Number | Physical Pin | Function | Direction | Notes |
|----------|------------|--------------|----------|-----------|-------|
| GPIO17 | 17 | 11 | Shutdown Button | Input | Pull-up, active low |
| GPIO27 | 27 | 13 | Status LED | Output | Active high |

### Shutdown Button

- **Pin**: GPIO17 (BCM numbering)
- **Type**: Momentary push button
- **Wiring**: Connect between GPIO17 and GND
- **Pull-up**: Internal pull-up enabled (reads HIGH when not pressed)
- **Behavior**:
  - Short press (< 3 seconds): Log event, no action
  - Long press (>= 3 seconds): Trigger graceful shutdown
- **Debounce**: 200ms software debounce

### Status LED

- **Pin**: GPIO27 (BCM numbering)
- **Type**: Standard LED with current-limiting resistor
- **Wiring**: Anode to GPIO27 via 330-ohm resistor, cathode to GND
- **Behavior**:
  - Solid ON: System running normally
  - Blinking: Shutdown pending or warning condition
  - OFF: System halted or not running

### GPIO Code Example (gpiozero)

```python
from gpiozero import Button, LED
from signal import pause

# Shutdown button on GPIO17
shutdown_button = Button(17, pull_up=True, bounce_time=0.2, hold_time=3)

# Status LED on GPIO27
status_led = LED(27)

def on_long_press():
    print("Long press detected, initiating shutdown...")
    # Trigger graceful shutdown

shutdown_button.when_held = on_long_press
status_led.on()  # Indicate system running
```

---

## Display: OSOYOO 3.5" HDMI Touch Screen

### Specifications

| Specification | Value |
|---------------|-------|
| Model | OSOYOO 3.5 inch HDMI Capacitive Touch Screen |
| Resolution | 480 x 320 pixels |
| Interface - Video | HDMI (plug and play) |
| Interface - Touch | USB (capacitive multi-touch) |
| Touch Type | Capacitive (no stylus required) |
| Compatibility | Raspberry Pi 5, 4, 3B, Jetson Nano, PC |

### Connection

1. **Video**: Connect HDMI cable from display to Pi's HDMI port
2. **Touch**: Connect USB cable from display to Pi's USB-A port
3. **Power**: Display powered via HDMI/USB (no separate power needed)

### Display Configuration

The display is plug-and-play on Raspberry Pi OS. If rotation is needed:

```bash
# /boot/firmware/config.txt
# Rotate display 180 degrees if mounting upside-down
display_hdmi_rotate=2
```

### UI Design Guidelines

- **Font Size**: Minimum 18pt for readability
- **Button Size**: Minimum 60x60 pixels for touch targets
- **Color Scheme**: High contrast (white text on dark background)
- **Refresh Rate**: 1-2 Hz to reduce CPU load
- **Resolution**: Design for 480x320 native resolution
- **Interactions**: Avoid hover effects; use tap/press only

---

## Wiring Diagram

```
+------------------+          +------------------+
|   Car Ignition   |          |   OSOYOO 3.5"    |
|    USB Charger   |          |  Touch Display   |
+--------+---------+          +--------+---------+
         |                             |
         | USB-C (5V)                  | HDMI + USB
         v                             v
+------------------+          +------------------+
|                  |          |                  |
|   X1209 UPS HAT  |          |  Raspberry Pi 5  |
|                  |          |                  |
|   +----------+   |          |  +-----------+   |
|   | 18650    |   |          |  | HDMI Port |<--+ (Video)
|   | Battery  |   |          |  +-----------+   |
|   +----------+   |          |  +-----------+   |
|                  |          |  | USB-A     |<--+ (Touch)
|   I2C: SDA/SCL --+--------->+->| GPIO      |   |
|   (0x36)         |          |  +-----------+   |
|                  |          |                  |
|   USB-C Out -----+--------->+->| USB-C PWR |   |
|   (5.1V/5A)      |          |  +-----------+   |
+------------------+          +------------------+
                                       |
                                       v
                              +------------------+
                              |  GPIO Peripherals|
                              |                  |
                              |  GPIO17 (Pin 11) |<--- Shutdown Button
                              |       |          |     (to GND)
                              |       v          |
                              |   [BUTTON]       |
                              |       |          |
                              |      GND         |
                              |                  |
                              |  GPIO27 (Pin 13) |--->  Status LED
                              |       |          |      (330 ohm)
                              |       v          |        |
                              |    [LED+]        |        v
                              |       |          |      [LED]
                              |      GND         |        |
                              |                  |       GND
                              +------------------+
```

### Physical Pin Layout (Relevant Pins)

```
        +---+---+
   3.3V | 1 | 2 | 5V
   SDA1 | 3 | 4 | 5V
   SCL1 | 5 | 6 | GND
  GPIO4 | 7 | 8 | TX
    GND | 9 |10 | RX
 GPIO17 |11 |12 | GPIO18    <-- Pin 11: Shutdown Button
 GPIO27 |13 |14 | GND       <-- Pin 13: Status LED
        +---+---+
        ...
```

### Connection Summary

| Component | Interface | Pi Connection |
|-----------|-----------|---------------|
| X1209 UPS HAT | I2C (SDA/SCL) | GPIO2/GPIO3 (Pins 3/5) |
| X1209 UPS HAT | Power Out | USB-C |
| OSOYOO Display | Video | HDMI |
| OSOYOO Display | Touch | USB-A |
| Shutdown Button | GPIO | GPIO17 (Pin 11) + GND |
| Status LED | GPIO | GPIO27 (Pin 13) + GND |

---

## Platform-Specific Code Paths

### Overview

The Eclipse OBD-II system runs on both Windows (development) and Raspberry Pi (production). Hardware-specific modules are conditionally loaded based on platform detection.

### Platform Detection

```python
# src/hardware/platform_utils.py (to be implemented)
def isRaspberryPi() -> bool:
    """Check if running on Raspberry Pi."""
    # Check /proc/cpuinfo for Raspberry Pi model
    # Check /sys/firmware/devicetree/base/model
    # Return False on Windows/Mac for graceful fallback

def getPlatformInfo() -> dict:
    """Get detailed platform information."""
    # Returns: os, architecture, model (if Pi)
```

### Conditional Hardware Loading

```python
from hardware.platform_utils import isRaspberryPi

if isRaspberryPi():
    from hardware.ups_monitor import UpsMonitor
    from hardware.gpio_button import GpioButton
    from hardware.status_display import StatusDisplay
else:
    # Use mock/stub implementations for development
    pass
```

### Hardware Module Fallback Behavior

| Module | On Raspberry Pi | On Windows/Mac |
|--------|-----------------|----------------|
| `platform_utils` | Returns actual Pi info | Returns False, generic info |
| `i2c_client` | Uses smbus2 for I2C | Raises clear exception |
| `ups_monitor` | Reads real battery data | Uses mock/disabled |
| `gpio_button` | Monitors real GPIO | Logs warning, disabled |
| `status_display` | Renders to HDMI | Uses mock/disabled |

---

## Requirements

### Pi-Specific Python Packages

See [requirements-pi.txt](../requirements-pi.txt) for the complete list:

```
# Hardware - Raspberry Pi Specific
smbus2>=0.4.0                 # I2C communication
RPi.GPIO>=0.7.1               # GPIO pin control
gpiozero>=2.0.0               # High-level GPIO (recommended)
adafruit-circuitpython-rgb-display>=3.10.0  # Display drivers
Pillow>=10.0.0                # Image processing
pygame>=2.0.0                 # Display rendering and touch
```

### System Packages (apt)

```bash
sudo apt install -y \
    python3-pip \
    python3-smbus \
    i2c-tools \
    python3-gpiozero \
    python3-pil \
    python3-pygame
```

---

## Error Handling

### I2C Communication Errors

- **Retry Strategy**: 3 retries with exponential backoff (1s, 2s, 4s)
- **Error Classification**: I2C errors are retryable
- **Fallback**: If I2C fails, log warning and disable UPS monitoring

### Power Loss Detection

- **Primary Method**: I2C telemetry (power source register)
- **Fallback Method**: GPIO interrupt (if X1209 provides signal)
- **Shutdown Delay**: 30 seconds after power loss detected
- **Low Battery**: Immediate shutdown if battery < 10%

### GPIO Errors

- **Non-Pi Detection**: Log warning, return gracefully
- **Pin Conflict**: Raise ConfigurationError with clear message

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-25 | Ralph Agent | US-RPI-001: Initial hardware reference documentation |
