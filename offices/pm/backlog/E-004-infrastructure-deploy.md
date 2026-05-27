---
id: E-004
status: active
createdAt: 2026-05-27
---

# E-004 — Infrastructure & Deploy

## Description
The plumbing: Pi 5 + server deployment + sync + power management + hostnames + clock
sync + simulator infrastructure + service orchestration. This Epic owns everything
that makes the system run reliably in the car or on the bench, distinct from what
data flows through it (E-002) or how users see it (E-001).

## Features
Pi foundation (8 features complete): F-002 application orchestration, F-010 Pi target
docs, F-012 Pi 5 initial setup, F-013 CI/CD Win→Pi deploy, F-014 Pi simulator+real OBD
testing, F-023 WiFi-triggered auto-sync, F-027 Pi→server sync, F-SIM simulator mode,
F-045 physics→flat-file replay.

V0.27 active (3 features): F-037 Pi crawl/walk/run pipeline, F-043 auto-sync+
conditional-shutdown on power loss, F-044 config-driven addresses (standing rule).

V0.28+ (6 features pending): F-047 Pi self-update from server registry, F-063 Pi 5
fuse-box buck converter (replaces stereo USB-C tap), F-075 drive_statistics Pi-side
writer (Spool's Approach 2), F-080 Pi clock drift post-reboot (Spool's Bug 5),
F-102 hostname resolution cleanup (chi-eclipse-01 / chi-srv-01 LAN-wide).

## Context / rationale
Network: 10.27.27.0/24 LAN. Pi 5 at 10.27.27.28 (current hostname Chi-Eclips-Tuner;
rename to chi-eclipse-01 pending in F-102). Chi-Srv-01 at 10.27.27.10 (i7-5960X,
128GB RAM, 12GB GPU, MariaDB + Ollama). Power topology: battery → fuse → Geekworm
X1209 UPS → Pi. Multiple key-on/key-off cycles per outing are normal; F-043
sequencer + EEPROM=1 lock landed in V0.27 chain to handle this.
