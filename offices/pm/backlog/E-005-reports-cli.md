---
id: E-005
status: pending
createdAt: 2026-05-27
---

# E-005 — Reports & CLI

## Description
Data export, CLI tooling, and driver-facing reports. This Epic owns the export paths
out of the system (Excel, audio, text reports), the Ollama report-generation behavior,
and CLI helpers for PM/Spool to query the data store directly.

## Features
- F-003 Document and Verify Ollama Fallback Behavior (pending)
- F-041 Analytics Excel Export CLI (pending)
- F-091 GEM-6 — Audio Drive Reports via Android Auto (pending)

## Context / rationale
CIO preference: human-readable text reports on Chi-Srv-01 first; "get it working then
format/delivery" (simple). Comparison style: always have a baseline, trend-oriented
("are we getting better?"). Reports tier currently lightweight — most analytics
consumption is via direct SQL/Spool queries against MariaDB. Audio drive reports
(F-091) target Android Auto when the CIO has a laptop in the car with ECMLink
running — driver hears Spool-grade summary while still on the road.
