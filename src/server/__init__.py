"""
Companion service tier package (Chi-Srv-01).

Contains modules deployed to the home analysis server only:
- FastAPI web app (api/)
- Upload ingestion and delta sync (ingest/)
- AI analysis (ai/)
- Post-drive deep analysis (analysis/)
- Recommendation staging (recommendations/)
- MariaDB models and schema (db/)

Not deployed to the Raspberry Pi. Imports from `src.common` are allowed;
imports from `src.pi` are forbidden (enforced structurally — `src.pi`
won't exist on the deployed server).
"""
