# Issue: Type Safety and Interface Contracts in Orchestrator

**Reported by**: Rex (Agent 1)
**Date**: 2026-01-29
**Priority**: Medium
**Type**: Code Quality / Specs Update Request

---

## Problem

The orchestrator (and likely other modules) has two related design concerns discovered during deep-dive analysis:

### 1. Optional[Any] Types Everywhere

All 12 component references in the orchestrator are typed as `Optional[Any]`:
```python
self._database: Optional[Any] = None
self._connection: Optional[Any] = None
self._dataLogger: Optional[Any] = None
# ... 9 more
```

This eliminates all type checking benefits. MyPy can't catch interface mismatches, and IDE autocomplete doesn't work.

### 2. 30+ hasattr() Calls for Duck Typing

Instead of formal interfaces, the orchestrator checks method existence at runtime:
```python
if hasattr(self._displayManager, 'showAlert'):
    self._displayManager.showAlert(alertEvent)
```

This is fragile -- if a method is renamed or removed, no static analysis catches it. Errors only appear at runtime.

## Proposed Solution

Define `Protocol` classes (PEP 544) for component interfaces:
```python
from typing import Protocol

class DisplayManagerProtocol(Protocol):
    def showAlert(self, alertEvent: Any) -> None: ...
    def showConnectionStatus(self, status: str) -> None: ...
    def updateValue(self, param: str, value: float, unit: str) -> None: ...
```

Then type the orchestrator properly:
```python
self._displayManager: Optional[DisplayManagerProtocol] = None
```

## Specs Impact

If adopted, this pattern should be added to:
- `specs/standards.md` - New section on interface contracts
- `specs/anti-patterns.md` - Add "hasattr() for interface checking" as anti-pattern

## Recommendation

Address this during the orchestrator refactoring (TD-003). The new `types.py` module in the split is a natural home for Protocol definitions.

---

*Submitted by Rex via pm/issues/ per read-only specs/ protocol.*
