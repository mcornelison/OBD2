"""
Tuning recommendation wire format.

Will eventually contain:
- Recommendation: a tuning adjustment proposed by the server, staged for
  CIO review before any ECMLink action. Includes severity, rationale,
  before/after values, and a unique ID.
- RecommendationStatus: enum (pending, reviewed, accepted, rejected, applied)
- RecommendationSource: enum (statistical, spool_ai, manual)

IMPORTANT: Recommendations are ALWAYS staged for human review, never
auto-applied to the ECU. See CLAUDE.md architectural decision #2.

Populated post-reorg when the server analysis pipeline (B-031) is built.
"""
