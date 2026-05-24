---
name: PM uses Python scripts for repeatable/deterministic tools (token efficiency)
description: For mechanical, repeatable, deterministic operations (status field bumps, JSON reconciliation, archive timestamping, version checks, lint runs, deploy verifies), PM (Marcus) uses Python scripts in offices/pm/scripts/ instead of inline shell or python -c blocks. Saves CIO tokens and gets correct results.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
CIO 2026-05-05 standing rule: "to minimize token use and save the tokens, use python code to perform repeatable / deterministic tools and utilities."

**Scope**: PM office (`offices/pm/`) and PM-driven workflows ONLY. Do NOT propose Python utility refactors in `offices/ralph/`, `offices/tuner/`, or other agent folders.

**Do NOT pre-extract aggressively**: CIO 2026-05-05: "no need to be aggressive, we can resolve things going forward organically." When a slash command or ritual uses inline `python -c` for now, leave it -- extract to a script in `offices/pm/scripts/` only when the script's logic is reused by a 2nd caller OR when the inline block grows beyond ~10 lines OR at the next sprint-close cycle naturally. Rule applies organically, not with pre-emptive cleanup passes.

**Why**:
- Inline shell + `python -c` blocks consume tokens on every invocation (the script body is in every PM message)
- Python scripts in `offices/pm/scripts/` are written once + invoked with a one-line command + their bodies don't reappear in messages
- Deterministic operations (JSON edits, timestamping, file-existence checks, schema validations) belong in tested, version-controlled scripts -- not ad-hoc shell loops that drift across invocations
- Existing tools `pm_status.py`, `backlog_set.py`, `sprint_lint.py` already establish the pattern; extend it.

**How to apply** during grooming, sprint operations, and ritual execution:

- BEFORE writing inline `python -c "..."` or chained shell loops, ask: "is this a one-shot or will I do it again?" If 2+, write a script.
- BEFORE writing a slash command that uses bash for mechanical work, ask: "could each phase be a `python offices/pm/scripts/<name>.py` invocation?" Yes -> refactor first.
- Place new scripts in `offices/pm/scripts/<verb-noun>.py` matching existing convention (`pm_status.py`, `sprint_lint.py`, `backlog_set.py`).
- Add `--help` / argparse to every new script so future invocations are self-documenting.
- Cross-link from `offices/pm/scripts/README.md` (if it exists) or `projectManager.md` Tools section.

**Examples of operations that should be Python scripts** (most already are):
- `pm_status.py` -- sprint + backlog + counter snapshot (already exists)
- `sprint_lint.py` -- Sprint Contract v1.0 audit (already exists; US-274 + US-282 extensions live here)
- `backlog_set.py` -- backlog mutation CLI (already exists)
- **Status field hygiene bump** (Phase 1 of `/sprint-close-pm`) -- currently inline `python -c` in slash command; should be `pm_status_bump.py`
- **Archive sprint.json + progress.txt with UTC timestamp** (Phase 2 of `/sprint-close-pm`) -- currently bash + inline python; should be `archive_sprint_artifacts.py`
- **RELEASE_VERSION 400-char check** (Phase 6 of `/sprint-close-pm`) -- currently inline python; should be `verify_release_version.py`
- **Deploy-target version verify** (Phase 8 of `/sprint-close-pm`) -- currently shell ssh + grep; should be `verify_deployed_version.py`
- **Backlog closure-in-fact reconciliation** (Sprint 25 Bucket A audit) -- I did this inline; if the pattern recurs, extract `reconcile_closed_backlog.py`

**Anti-patterns to avoid**:
- Long `python -c` blocks for non-trivial logic (anything >10 lines belongs in a file)
- Chained `for f in ...; do ...; done` shell loops that mutate JSON or files (race conditions + no error handling)
- Re-implementing logic that's already in `offices/pm/scripts/` (audit before writing new code)
- Bash arithmetic / date manipulation / JSON parsing (use Python; bash is for orchestration only)

**When inline IS appropriate**:
- One-time exploratory queries (`python -c "import json; print(json.load(open('foo.json'))['key'])"`)
- Quick verification commands during debugging
- Trivial one-line operations

**Refactor backlog as standing TD**:
The `/sprint-close-pm` slash command (shipped 2026-05-05) uses bash for Phase 2 archive + inline python for Phase 6 version-check. Per this rule, those should be extracted to `offices/pm/scripts/archive_sprint_artifacts.py` + `offices/pm/scripts/verify_release_version.py`. File as PM standing TD; address before next sprint-close uses the command.
