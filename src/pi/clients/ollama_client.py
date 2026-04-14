"""
Thin HTTP client for the remote Ollama instance (or the companion service's
/api/chat endpoint once it exists).

Will eventually contain:
- OllamaClient: a connection manager + request helper
- chat(): synchronous prompt→response helper
- isAvailable(): quick health check

Populated when the Pi needs to request AI analysis from the server.
This replaces the temporary direct import of src.server.ai.ollama_manager
documented in TD-reorg-sweep3-ollama-boundary.md.
"""
