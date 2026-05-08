# Ralph Agent System

Automates coding tasks for the Eclipse OBD-II Performance Monitoring System. Coordinates multiple agents working through user stories from `sprint.json`.

## Folder Contents

| File | Purpose |
|------|---------|
| `prompt.md` | **Headless contract** — full per-iteration instructions injected into `claude -p` |
| `CLAUDE.md` | **Interactive context** — loaded by `/init-ralph` (architecture, tier rules, knowledge index) |
| `agent-pi.md` | Pi 5-specific agent instructions (Torque) |
| `agent.py` | Agent management CLI (`getNext`, `list`, `sprint`, `clear`) |
| `ralph.sh` | Shell launcher — runs N iterations, parses `<promise>` tags |
| `sprint.json` | Active sprint user stories (US-* prefixed) |
| `ralph_agents.json` | Per-agent assignment + last-session note |
| `progress.txt` | Rolling session log (older entries → `archive/progress.archive.YYYY-MM-DD.txt`) |
| `knowledge/` | Load-on-demand topic patterns (testing, hardware, OBD, sync, systems) |
| `inbox/` | PM/Spool/Tester messages (interactive review) |
| `archive/` | Date-stamped historical artifacts |

## Quick Start

```bash
./ralph.sh status      # Sprint progress + agent assignments (no agent spawn)
./ralph.sh 5           # Run 5 iterations
./ralph.sh help        # Help
```

## How One Iteration Works

`ralph.sh` loops N times. Each iteration:

1. Picks the first unassigned agent from `ralph_agents.json` via `agent.py getNext`.
2. Injects `sprint.json` + `progress.txt` + `prompt.md` content into `claude -p`.
3. Agent picks one story, implements with TDD, runs tests + lint, updates `sprint.json` + `ralph_agents.json` + appends to `progress.txt`, exits.
4. `ralph.sh` parses `<promise>` tags from agent output to decide whether to continue, stop normally, or stop with PM-attention exit code 1.

`<promise>` tag contract is in `prompt.md` §Stop Condition (authoritative — `ralph.sh` string-matches against those exact tokens).

## Agent Management CLI

```bash
python offices/ralph/agent.py list          # Agents + status
python offices/ralph/agent.py sprint        # Story breakdown (complete / blocked / available)
python offices/ralph/agent.py getNext       # First unassigned agent (used by ralph.sh)
python offices/ralph/agent.py clear 1       # Release agent 1
python offices/ralph/agent.py clear all     # Release all agents
```

## If `ralph_agents.json` Gets Out of Sync

Symptoms: agents cannot be assigned, duplicate assignments, agent.py errors.

1. Open `ralph_agents.json` and verify: `max_agent` matches active slots; each agent has unique `id`, valid `status` (`unassigned` / `active`), and `taskid`.
2. Reset: `python offices/ralph/agent.py clear all`.
3. Validate JSON syntax (any linter).
4. Confirm: `python offices/ralph/agent.py list`.

## Tips

- Run scripts from the project root.
- Check `progress.txt` for recent reusable patterns before starting.
- Use `./ralph.sh status` between runs to monitor progress.
- For interactive sessions, run `/init-ralph` to load full context.
