################################################################################
# File Name: __init__.py
# Purpose/Description: EDR sensor-reader package (F-113). Polls the two I2C
#                      sensors (ICM-20948 IMU @0x69, TSL2591 light @0x29) and
#                      publishes them onto the F-110 SampleBus as additive
#                      LOSSY channels. Pi-tier only.
# Author: Rex (US-409)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""EDR sensor readers (IMU + light) for the Pi SampleBus."""
