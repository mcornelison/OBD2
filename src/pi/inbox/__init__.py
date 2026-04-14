"""
Pi-side recommendation inbox reader.

Recommendations from the server land in a file-based inbox on the Pi
(see CLAUDE.md architectural decision #2 — never auto-apply to ECU).
This package reads them for display / CIO review.

Implementation lands with the first server→Pi recommendation flow.
"""
