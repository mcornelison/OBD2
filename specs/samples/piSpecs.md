# Raspberry Pi 5 Car-Powered System – Technical Specifications and Developer Guide

This document provides a complete technical specification and developer reference for the Raspberry Pi 5 car-powered system using the Geekworm X1209 UPS HAT and OSOYOO 3.5" HDMI Capacitive Touch Screen. It includes architecture, power management, telemetry, display integration, logging, and software module guidance.

---

## 1. System Architecture Overview

- **Platform**: Raspberry Pi 5 (8GB)
- **Operating System**: Raspberry Pi OS (64-bit)
- **Primary Interfaces**:
  - USB-C for power input/output
  - GPIO for shutdown button
  - I²C for UPS telemetry
  - HDMI for display output
  - USB for touch input
- **Storage**: 128GB A2 U3/V30 microSD (high-endurance)

---

## 2. Display

- **Model**: OSOYOO 3.5 inch HDMI Capacitive Touch Screen
- **Interfaces**:
  - HDMI for video output
  - USB for capacitive touch input
- **Compatibility**:
  - Raspberry Pi 5, 4, 3B, Jetson Nano, PC
  - Operating Systems: Raspberry Pi OS, Ubuntu, Kali, Windows 11/10/8/7
- **Features**:
  - Plug and play HDMI display
  - Capacitive multi-touch support via USB
  - No driver required for display output
  - USB touch input may require calibration depending on OS

### Touch Integration Notes

- **Touch Interface**: USB HID (Human Interface Device)
- **Touch Libraries**:
  - `evdev` for low-level event handling
  - `pygame` or `tkinter` for GUI and touch interaction
- **Calibration**:
  - Most Raspberry Pi OS builds auto-detect USB touch
  - If needed, use `xinput_calibrator` or `evtest` for manual calibration
- **Best Practices**:
  - Use large buttons and high-contrast UI
  - Avoid hover-based interactions
  - Optimize for 480x320 resolution
  - Use full-screen mode to maximize touch area

---

## 3. Power Management Workflow (X1209 UPS HAT)

- **Power Input**: 5V via USB-C (car ignition or wall adapter)
- **Battery Backup**: Single protected 18650 Li-ion cell
- **Output**: 5.1V / 5A USB-C to Raspberry Pi
- **UPS Features**:
  - Automatic switchover to battery on power loss
  - I²C telemetry for voltage, current, battery status
  - Safe shutdown trigger via GPIO or I²C
  - Auto power-on when external power is restored

---

## 4. Boot and Shutdown Logic

### Boot Sequence
1. Car ignition supplies 5V via USB-C
2. X1209 powers Raspberry Pi 5
3. Pi boots and initializes services
4. Display shows system status

### Shutdown Sequence
1. Car ignition turns off (external power loss)
2. X1209 switches to battery
3. Software detects power loss via I²C or GPIO
4. Graceful shutdown initiated within 30–60 seconds
5. Pi halts and X1209 cuts power after shutdown

---

## 5. Telemetry Interfaces

- **I²C Bus**:
  - Battery voltage
  - Charge/discharge current
  - Power source status (external vs battery)
  - Battery charge percentage
- **GPIO**:
  - Input: Momentary shutdown button
  - Output: Optional status LED or buzzer

---

## 6. Software Modules

- `power_monitor.py`:
  - Polls X1209 telemetry via I²C
  - Detects power source changes
  - Triggers shutdown sequence

- `shutdown_button.py`:
  - Monitors GPIO pin for button press
  - Initiates safe shutdown

- `logger.py`:
  - Logs telemetry and system events to disk
  - Rotates logs daily or by size

- `display_status.py`:
  - Outputs system status to HDMI display
  - Shows power source, battery %, uptime, IP address
  - Handles touch input for interactive UI

- `startup.service` and `shutdown.service`:
  - systemd units to manage startup/shutdown behavior

---

## 7. Data Logging Requirements

- **Log Format**: JSON or CSV
- **Log Frequency**: Every 10 seconds
- **Data Points**:
  - Timestamp
  - Power source (external/battery)
  - Battery voltage (V)
  - Battery current (mA)
  - Battery percentage (%)
  - System uptime
  - CPU temperature
  - Free disk space
- **Storage Location**: `/var/log/carpi/`
- **Retention Policy**: 365 days

---

## 8. Error Handling

- **Power Loss Detection Failure**:
  - Fallback to GPIO-based detection
  - Log error and attempt shutdown after timeout

- **I²C Communication Error**:
  - Retry up to 3 times
  - Log error and alert via display

- **Low Battery Condition**:
  - If battery < 10%, initiate immediate shutdown
  - Log critical warning

- **Filesystem Errors**:
  - Log to emergency file
  - Attempt remount or reboot if safe

---

## 9. Integration Points

- **External Display**:
  - HDMI output for real-time status
  - USB touch input for interactive UI
  - Optional: rotate display for dashboard mounting

- **Vehicle Ignition**:
  - USB-C PD adapter connected to ignition-switched outlet

- **Cloud Sync (Optional)**:
  - Upload logs via Wi-Fi when available
  - Use rsync or MQTT for remote monitoring

- **OTA Updates (Optional)**:
  - Git-based deployment of software modules
  - Version tracking via Git tags

---

## 10. Developer Tips and Recommendations

- Design for interruption: flush logs frequently
- Use modular code for telemetry, logging, display, shutdown
- Retry I²C reads with exponential backoff
- Avoid blocking calls in power monitoring
- Test with real power cuts
- Use large UI elements for touch
- Avoid hover or right-click interactions

---

## 11. Recommended Python Libraries

| Purpose | Library | Notes |
|--------|---------|-------|
| I²C Communication | `smbus2` | Lightweight and compatible with Pi |
| GPIO Handling | `RPi.GPIO`, `gpiozero` | `gpiozero` is higher-level |
| Logging | `logging` | Built-in Python module |
| Display Output | `pygame`, `tkinter`, `PIL` | For rendering to HDMI |
| Touch Input | `evdev`, `pygame`, `tkinter` | For USB capacitive touch handling |

---

## 12. Library Installation Notes

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-smbus i2c-tools python3-gpiozero python3-pil
sudo apt install -y python3-pygame python3-tk python3-evdev
```

---

## 13. UPS HAT (X1209) Integration Tips

- Poll every 5–10 seconds
- I²C address typically 0x36 or 0x57
- Monitor power source and battery voltage
- Begin shutdown within 30–60 seconds of power loss
- Shutdown before battery drops below 3.0V

---

## 14. Display Integration Tips

- Use `pygame` or `tkinter` for full-screen UI
- Optimize for 480x320 resolution
- Use `evdev` to capture touch events
- Calibrate touch if needed using `xinput_calibrator`
- Avoid full desktop environment for performance
- Refresh display at 1–2 Hz to reduce load

---

## 15. Logging and Data Management

- Use `RotatingFileHandler` or `logrotate`
- Rotate daily or at 5–10MB
- Buffer logs in RAM and flush periodically
- Avoid excessive SD card writes

---

## 16. Systemd Integration Tips

- Use `startup.service` to launch scripts at boot
- Use `shutdown.service` to handle GPIO/I²C shutdown
- Use `Restart=on-failure` for critical services
- Use `TimeoutStopSec=30` for clean shutdown

---

## 17. Optional Enhancements

- Cloud sync via rsync or MQTT
- Remote monitoring dashboard
- OTA updates via Git and cron
- Touch-based menu for diagnostics or reboot

---