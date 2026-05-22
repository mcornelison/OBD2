"""Server-side CLI surface (US-350 / B-104 Step 1a).

Modules:
    recompute_drive_analytics -- on-demand recompute of drive_summary +
        drive_statistics from raw realtime_data.  Invoked by the nightly
        systemd batch service AND directly by operators for backfill /
        single-drive recompute.
"""

from __future__ import annotations
