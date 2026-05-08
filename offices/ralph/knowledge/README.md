# Ralph Knowledge Base

Ralph-specific knowledge files. Loaded on-demand by `/init-ralph`, NOT all at startup.

**Rule:** Shared auto-memory (`.claude/projects/.../memory/`) is for cross-agent facts only. Ralph's detailed knowledge lives HERE so it doesn't pollute other agents' context.

## Index

### Always-loaded at init
None of these files are loaded at init. The always-loaded core is:
- Headless: `offices/ralph/prompt.md` (injected into `ralph.sh` per iteration).
- Interactive: `offices/ralph/CLAUDE.md` (loaded by `/init-ralph`).

This directory is the lazy layer.

### Process + rules (load when a process question arises)
- `sprint-contract.md` — sprint.json schema, 5 refusal rules, sizing caps, reviewer discipline, banned phrases
- `session-learnings.md` — accumulated learnings across sessions (gotchas, patterns, CIO feedback)
- `codebase-architecture.md` — orchestrator package structure, config patterns, tier layout
- `sweep-history.md` — reorg sweep summaries (load only when referencing prior reorg work)

### Code patterns (load when a story touches the topic)
- `patterns-pi-hardware.md` — I2C, GPIO, UPS/MAX17048/EXT5V, pygame, OSOYOO, system telemetry, hardware abstraction, display color coding
- `patterns-testing.md` — mocking (capsys, class/instance, argparse --help), Windows CSV/path, test debugging, pytest platform gates (collect_ignore_glob + pi_only), Windows Python cold-start flake, adafruit 3.13 flake, deterministic SQLite fixtures, bash driver testing
- `patterns-obd-data-flow.md` — drive detection state machines, session lifecycle gotchas, simulator scenario quirks + patterns, database patterns, VIN decoding, text similarity (Jaccard + variance)
- `patterns-sync-http.md` — DNS reverse-lookup patterns, Pi→server HTTP sync (HWM preservation, 4xx-except-429 classifier, injection seams, urllib, header capitalization, bool-vs-int guard)
- `patterns-python-systems.md` — threading (Timer, Event.wait, exception-safe polling), config dot-notation, signal handling, path resolution, logging (unique loggers, RotatingFileHandler), Ollama/AI integration, destructor safety, export patterns, profile pending-switch, module refactoring (structure, BC re-exports, patch targeting, circular imports, name collisions), git show for deleted files, systemd service patterns (venv/install decoupling, journald, idempotent install, grep-acceptance gotcha, StartLimit section placement, offline-vs-runtime correctness, python-OBD shadowing)

### Archival (load only if a future story specifically needs these)
- `legacy-admonitor-patterns.md` — scapy/Npcap + hosts-file/EasyList blocklist patterns carried over from the adMonitor precursor project. NOT loaded at startup. Reference only if a future story needs packet capture or blocklist parsing.

## File-size policy

All files in this directory target ≤400 lines. If a file exceeds that, split it into sibling files and update this index.

## Load-on-demand decision rule

When a sprint story lands, scan its `scope.filesToRead` and `intent`. If the story touches:
- Pi hardware (I2C, GPIO, UPS, display) → load `patterns-pi-hardware.md`
- Tests or test infrastructure → load `patterns-testing.md`
- OBD polling, drive detection, simulator, DB writes → load `patterns-obd-data-flow.md`
- Pi→server sync or HTTP clients → load `patterns-sync-http.md`
- Python stdlib / systemd / Ollama / module refactoring → load `patterns-python-systems.md`
- Sprint contract or process question → load `sprint-contract.md` + `session-learnings.md`
- Code navigation across tiers → load `codebase-architecture.md`

Do NOT load every file at session start. The One Source of Truth rule in `sprint-contract.md` applies: the sprint story's `scope.filesToRead` is the context boundary.
