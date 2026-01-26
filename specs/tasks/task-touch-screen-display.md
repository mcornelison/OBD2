# Task: Implement Touch Screen Display Support

## Summary
Add support for the OSOYOO 3.5" HDMI capacitive touch screen for the Raspberry Pi deployment.

## Background
The Pi 5 build includes an OSOYOO 3.5" HDMI touch screen:
- Resolution: 480x320
- Interface: HDMI for video, USB for touch
- Touch: Capacitive multi-touch via USB HID

Currently, the display system supports:
- `headless` - No display
- `minimal` - Basic terminal output
- `developer` - Detailed console logging
- `adafruit` - Adafruit 1.3" SPI display (240x240)

Need to add support for the HDMI touch screen.

## Hardware Specs (from piSpecs.md)
- **Model**: OSOYOO 3.5 inch HDMI Capacitive Touch Screen
- **Resolution**: 480x320
- **Video**: HDMI (plug and play)
- **Touch**: USB HID (capacitive, multi-touch)
- **OS Support**: Raspberry Pi OS, no driver needed

## Implementation Requirements

### New Display Driver
- [ ] `src/display/drivers/hdmi_touch.py` - HDMI touch screen driver
- [ ] Support 480x320 resolution
- [ ] Handle touch input via USB HID
- [ ] Full-screen mode for dashboard

### UI Considerations (from piSpecs.md)
- Large buttons (touch-friendly)
- High contrast colors
- No hover-based interactions
- Optimize for 480x320
- Refresh rate: 1-2 Hz to reduce load

### Touch Input Handling
- Use `evdev` or `pygame` for touch events
- Support tap gestures for button presses
- Consider swipe gestures for screen navigation
- Calibration support if needed (`xinput_calibrator`)

### Display Layout (480x320)
```
┌──────────────────────────────────────────────┐
│ Eclipse OBD-II          [D] Daily   12:34 PM │
├──────────────────────────────────────────────┤
│                                              │
│   RPM          TEMP         SPEED            │
│   2500         185°F        45 mph           │
│                                              │
│   A/F RATIO    BOOST        VOLTAGE          │
│   14.7:1       8.5 psi      12.4V            │
│                                              │
├──────────────────────────────────────────────┤
│ [Profile] [Alerts] [Export] [Settings]       │
└──────────────────────────────────────────────┘
```

### Libraries to Use
- `pygame` - Full-screen rendering and touch
- `PIL/Pillow` - Image manipulation
- `evdev` - Low-level touch events (if needed)

## Configuration
Add to `config.json`:
```json
{
  "display": {
    "mode": "hdmi_touch",
    "resolution": [480, 320],
    "fullscreen": true,
    "refreshRate": 2
  }
}
```

## Acceptance Criteria
- [ ] HDMI touch driver implemented
- [ ] Touch input works for button presses
- [ ] Full-screen dashboard displays correctly
- [ ] Profile switching via touch
- [ ] Settings accessible via touch
- [ ] Works alongside existing display drivers
- [ ] Configuration documented

## Dependencies
- `pygame` - Add to requirements-pi.txt
- `evdev` - Add to requirements-pi.txt (optional)

## Priority
Medium - New hardware feature

## Estimated Effort
Medium to Large - New driver and UI work

## Created
2026-01-25 - Tech debt review
