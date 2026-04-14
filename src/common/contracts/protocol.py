"""
Wire protocol envelope types.

Will eventually contain:
- protocolVersion: str constant (single source of truth)
- UploadEnvelope: the Pi→Server upload wire format
- HandshakeRequest / HandshakeResponse: version negotiation at upload time
- UploadStatus: success/reject/retry classification

Populated post-reorg when real data flow begins.
"""
