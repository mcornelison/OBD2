---
id: E-001
status: active
createdAt: 2026-05-27
---

# E-001 — UI/UX Polish

## Description
Pi-side display experience: boot/shutdown splash, touch UI, display tiles, dashboard
layout, on-screen warnings. The driver glances at the Pi screen during car operation;
UX matters for glance-readability + CIO confidence the system is healthy.

## Features
- F-007 Touch Screen Display Support (pending)
- F-030 Tuning-Driven Display Layout — 3.5" Touchscreen (complete)
- F-052 HDMI Dashboard Full-Canvas Redesign (pending)
- F-086 GEM-1 — Warnings-first quiet UI on the 3.5" display (pending)
- F-092 GEM-7 — System Status Tile (BT link, sync, power mode, ladder stage) (pending)
- F-096 S-2 — LTFT trend display, multi-drive healthy migration toward 0 (pending)
- F-097 S-3 — Drain Ladder State UI for UPS-battery condition (pending)
- F-103 Pi Splash Animation — Boot + Shutdown (pending; spec gated by Atlas v1.1)

## Context / rationale
The Pi 5 lives in the glovebox or trunk; the OSOYOO 3.5" HDMI display is dash-mounted
visible to the driver. Boot is a measurable user touchpoint (driver wants to know
the system is ready before connecting OBD2). Shutdown needs a graceful UX during the
power-loss grace period. GEM family items (Spool's tuning UX) move from raw thresholds
to driver-readable signals.
