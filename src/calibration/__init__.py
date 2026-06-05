################################################################################
# File Name: __init__.py
# Purpose/Description: Offline SPEED-PID GPS-calibration package. Reads a GPS
#                      "source of truth" track (Strava/Garmin FIT) and, with the
#                      matching OBD2 drive data, derives the per-ECU
#                      multiplicative SPEED correction factor for the
#                      speed_pid_calibration table. Offline analysis only -- NO
#                      Pi/server runtime module imports this package, and its
#                      fitparse dependency is tooling-only (absent from
#                      requirements-pi.txt / requirements-server.txt), so it
#                      never loads on the deployed tiers.
# Author: Atlas (Architect)
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
