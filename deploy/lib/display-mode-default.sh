#!/usr/bin/env bash
################################################################################
# deploy/lib/display-mode-default.sh -- what an ABSENT /etc/eclipse/display-mode
#                                       means (US-652-a / F-139)
#
# Sourced (never executed) by the FIVE shell readers of the mode file:
#   deploy/eclipse-display-mode.sh        read_mode
#   deploy/eclipse-capture-panel.sh       read_mode
#   deploy/deploy-pi.sh                   kiosk_mode_resolver
#   src/pi/ui/splash/install.sh           read_display_mode
#   src/pi/ui/dashboard/install.sh        read_display_mode
# Each one exits non-zero, nothing changed, when this file is missing -- never
# a silent fallback of its own.
#
# One fact, one home: the default used to be hard-coded in each reader, and
# US-652-b flips it, so it lives here and nowhere else. A file that EXISTS
# with any other content is the reader's business (each refuses it); this
# only answers for a file that is not there.
#
# Defines DISPLAY_MODE_DEFAULT and nothing else that runs.
################################################################################

DISPLAY_MODE_DEFAULT=x11
