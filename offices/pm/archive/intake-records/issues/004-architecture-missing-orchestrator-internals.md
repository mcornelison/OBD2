# Issue: Architecture Spec Missing Orchestrator Internals

**Reported by**: Rex (Agent 1)
**Date**: 2026-01-29
**Priority**: Low
**Type**: Documentation / Specs Update Request

---

## Problem

`specs/architecture.md` documents the high-level system components and data flows, but doesn't cover the orchestrator's internal structure -- which is the central coordination point of the entire application.

## What's Missing

### 1. Component Initialization Order
The exact dependency chain (Database -> ProfileManager -> Connection -> ... -> BackupManager) is not documented in architecture.md. It's only captured in `ralph/agent.md` tips and now in `ralph/progress.txt`. This is critical knowledge for anyone modifying startup/shutdown behavior.

### 2. Event/Callback Wiring
The data flow diagrams in Section 4 show the general pipeline but don't document how the orchestrator routes events between components via callbacks. For example, a single OBD reading fans out to 3 subsystems (display, drive detector, alert manager).

### 3. Connection Recovery Flow
The reconnection logic (exponential backoff, data logger pause/resume, thread management) is an important subsystem not mentioned in the architecture doc.

### 4. Shutdown Sequence
The reverse-order shutdown with timeout-based force-stop is a critical safety pattern (especially for Pi with UPS) that should be documented.

## Suggested Addition

Add a "Section 15: Application Orchestrator" to `specs/architecture.md` covering:
- Component lifecycle (init order, shutdown order)
- Event routing diagram
- Connection recovery state machine
- Shutdown sequence with timeouts

---

*Submitted by Rex via pm/issues/ per read-only specs/ protocol.*
