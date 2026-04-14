"""
Companion service entry point.

Placeholder — real FastAPI app wiring lands with B-022 (US-CMP-001 through
US-CMP-009). When populated, this file will:
- Load common config via src.common.config.validator
- Construct the FastAPI app from src.server.api.app
- Install API key middleware from src.server.api.middleware
- Register routes from src.server.api.health, ingest, recommendations
- Launch via uvicorn

For now, running this file is a no-op.
"""

if __name__ == "__main__":
    print("src/server/main.py is a placeholder. Real implementation lands with B-022.")
