"""
Pi-tier data-layer package.

Modules that own durable state on the Pi beyond the OBD-II collection
database: sync bookkeeping, future cache layers, etc.  Kept separate from
``src.pi.obd`` so sync-and-upload concerns do not drag OBD schema changes
into the sync contract (and vice versa).
"""
