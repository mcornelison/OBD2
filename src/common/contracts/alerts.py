"""
Alert event wire format.

Will eventually contain:
- AlertEvent: the wire representation of an alert firing (Pi-side event,
  uploaded to server for analysis history)
- AlertLevel: enum (normal, caution, danger)
- AlertParameter: enum of monitored parameters

Populated post-reorg.
"""
