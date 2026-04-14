"""
Drive log wire format.

Will eventually contain:
- DriveLog: a complete drive's telemetry (metadata + samples)
- Reading: single timestamped PID reading
- DriveSummary: aggregated stats attached to a drive
- DriveEventType: enum of drive lifecycle events

Populated post-reorg when real drive data starts flowing from the dongle.
"""
