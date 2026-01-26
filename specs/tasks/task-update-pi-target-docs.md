# Task: Update Raspberry Pi Target Documentation

## Summary
Update all documentation to reflect the actual target hardware: Raspberry Pi 5 with 64GB storage.

## Background
`specs/architecture.md` (line 90) currently says "Raspberry Pi 3B+/4" but the actual target hardware is:
- Raspberry Pi 5 (8GB RAM)
- 128GB microSD storage (per piSpecs.md)
- Geekworm X1209 UPS HAT
- OSOYOO 3.5" HDMI Capacitive Touch Screen (480x320)

## Files to Update
- [ ] `specs/architecture.md` - Update Hardware section (line 88-95)
- [ ] `CLAUDE.md` - Check for any Pi version references
- [ ] `docs/hardware-reference.md` - Verify consistency
- [ ] `README.md` - Update if hardware is mentioned

## Target Hardware Specs (from piSpecs.md)
- **Platform**: Raspberry Pi 5 (8GB)
- **Storage**: 128GB A2 U3/V30 microSD
- **Display**: OSOYOO 3.5" HDMI (480x320, USB touch)
- **Power**: Geekworm X1209 UPS HAT with 18650 battery
- **OS**: Raspberry Pi OS (64-bit)

## Acceptance Criteria
- [ ] All docs reference Pi 5 as target platform
- [ ] Hardware specs are consistent across all documentation
- [ ] No references to Pi 3B+/4 remain (except for compatibility notes)

## Priority
Low - Documentation update

## Estimated Effort
Small - Quick documentation update

## Created
2026-01-25 - Tech debt review
