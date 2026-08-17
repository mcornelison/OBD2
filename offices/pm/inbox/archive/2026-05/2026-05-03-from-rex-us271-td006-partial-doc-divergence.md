---
to: Marcus (PM)
from: Rex (Ralph Session 149)
date: 2026-05-03
re: US-271 deliberate-divergence -- TD-006 premise was partially false; .env.example already had OLLAMA_BASE_URL documented (just missing the remote-server example)
priority: low (informational; story shipped successfully)
---

# Summary

US-271 spec acceptance #1 said: `Pre-flight audit: rg \`OLLAMA_BASE_URL|ollamaBaseUrl\` .env.example config.json src/. Confirm config.json placeholder is in place + .env.example is missing the doc.`

**Pre-flight finding**: `.env.example` already documents `OLLAMA_BASE_URL` at line 81 (uncommented active default + 1-line description), in a "Server Configuration (Chi-Srv-01)" block added some time after TD-006 was filed (2026-02-05). The spec premise (`.env.example is missing the doc`) was *partially* false.

What WAS missing matched only one of TD-006's three suggested-fix lines: the **remote-server example** (`# OLLAMA_BASE_URL=http://10.27.27.10:11434`). That is the part that helps Pi deployers point at Chi-Srv-01.

# How I shipped

Per CIO standing rule "PM communication for missing stitching" + the deliberate-divergence pattern from US-272/273/274/277:

1. Confirmed config.json placeholder is in place at line 547 -- TD-006 first concern (hardcoded URL) is satisfied.
2. Honored spec invariant `Existing .env.example variable docs left untouched (additive only)` -- did NOT modify the existing line 81 `OLLAMA_BASE_URL=http://localhost:11434` or its description.
3. Added 4 commented lines after the existing stanza:
   ```
   # For Pi deployment, point at the remote Chi-Srv-01 instance instead:
   # OLLAMA_BASE_URL=http://10.27.27.10:11434
   # Resolved at runtime via the ${OLLAMA_BASE_URL:http://localhost:11434}
   # placeholder in config.json (server.ai.ollamaBaseUrl).  See US-OLL-001.
   ```
4. Marked TD-006 Resolved with closure section explaining what was already in place vs. what shipped.

Acceptance #2 (`contains a commented OLLAMA_BASE_URL stanza with default value + remote-server example`) is satisfied by the file overall: existing default line + new commented remote-server example.

# Why this is a Refusal Rule 1 non-trigger

Refusal Rule 1 (`ambiguity = blocker`) applies when spec **intent** is unclear. Here intent was unambiguous (document the override; help Pi deployers). What was off was the spec **premise** about the file's current state. Same shape as:

- **US-272** (rename target absent -- commit 57bdda6 had already deleted the test method)
- **US-273** (records already closed -- I-015/I-016/I-017 had Status:Closed pre-groom)
- **US-274** (US-278 phantom-path catch -- the check fired on a real divergence on its first run)
- **US-277** (/var/run ownership -- spec said root:root; shipped mcornelison:mcornelison since US-276 writer runs as User=mcornelison)

That's the **fifth** deliberate-divergence shipping in Sprint 23. Pattern is now stable enough to call it a sprint-mode rather than an exception.

# Why this happened (groom-knowledge gap)

TD-006 was filed 2026-02-05 referencing `obd_config.json:90` (which has since been replaced by `config.json` and the placeholder added). Subsequent work added `OLLAMA_BASE_URL` to `.env.example` (likely Sprint 7-9 server tier work; not tracked in TD-006). The TD record stayed open carrying the original 2026-02-05 description through 12 weeks of intervening work.

Same root-cause as US-273: TD records and reality drifted; record was never refreshed mid-flight even though the work was substantially done.

# Recommendation (carryforward, not blocking)

Same as US-273's inbox note: extend `sprint_lint.py` (or a sibling check) to read `filesToTouch` paths that point to TD records and detect already-closed Status, AND to spot-check file contents against the TD's "Current State" assertions. US-271's case is harder than US-273's pure-Status check because the assertion is content-comparison, not metadata. Lower-priority extension; flag only.

# Verification snapshot

- `grep -A4 OLLAMA_BASE_URL .env.example` -- shows existing default + new commented remote-server example + placeholder explanation
- `python offices/pm/scripts/sprint_lint.py --story US-271` -- 0 errors / 0 warnings
- ruff: 2 pre-existing errors in `scripts/seed_eclipse_vin.py` (B-044 violations already on main, OUT OF SCOPE per Refusal Rule 3); doc-only US-271 introduced ZERO ruff errors
- No source code, env-var-loading code, or `config.json` changes (doc-only per spec invariant)

# Files touched

- `.env.example` (UPDATE -- 4 commented lines added after line 82; existing line 81-82 untouched)
- `offices/pm/tech_debt/TD-006-env-example-ollama-base-url.md` (UPDATE -- Status: Resolved + Closure section)
- `offices/pm/inbox/2026-05-03-from-rex-us271-td006-partial-doc-divergence.md` (NEW -- this note)

PM action: none required; informational. The pattern and recommendation for future automation may be useful when grooming TD-heavy sprints.
