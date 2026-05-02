"""Pi diagnostics package -- post-mortem + introspection helpers.

US-263 introduces this package with :mod:`boot_reason`, a startup-log
writer that classifies the prior boot as clean (graceful shutdown
record present) vs hard crash (no shutdown record).  Future stories
may add boot-time hardware probes, journald rotation health, etc.
"""
