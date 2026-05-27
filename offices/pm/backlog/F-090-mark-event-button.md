---
id: F-090
parent: E-003
status: pending
renamedFrom: B-090
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-090: GEM-5 — MARK EVENT button (bookmark plus/minus 60s window for later analysis)

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (Spool Phase-3 V0.30)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | S        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Driver-side action; bookmarks plus/minus 60-second window around press; tagged for later analysis. Works in driving-glance UI (one big button); no distraction risk.

**Backend:** insert `event_marker` row tied to drive_id + timestamp + window_seconds; server analytics extracts the window for forensic review. Pairs naturally with the anomaly-explain Ollama prompt (B-087).

**Source:** Spool gem-filter PM note (GEM-5). CIO-approved.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
