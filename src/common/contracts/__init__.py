"""
Shared wire contracts for Pi↔Server data exchange.

All types in this package are imported by BOTH tiers and must not change
without a protocolVersion bump. See src/common/constants.py for the version.

**Current state: empty skeleton.** These files are placeholders. Real contract
types will be defined in a dedicated post-reorg task, once the Pi has actually
connected to the OBD-II Bluetooth dongle and we have real data to design against.
Defining contract types against hypothetical data shapes would bake in
assumptions that reality will contradict.
"""
