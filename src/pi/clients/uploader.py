"""
Drive log upload client — Pi pushes to the companion service.

Will eventually contain:
- Uploader: HTTP client that sends DriveLog payloads to the companion service
- delta sync logic (only unsent data)
- retry on network failure
- protocol version handshake (rejects upload on mismatch)

Populated by B-027 (Client-Side Sync to Chi-Srv-01).
"""
