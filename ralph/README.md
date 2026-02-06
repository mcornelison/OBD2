# Ralph Agent System

## Overview

The Ralph agent system automates coding tasks for the Eclipse OBD-II Performance Monitoring System. It coordinates multiple agents to work through a backlog of user stories, ensuring each agent works independently and progress is tracked.

## Folder Contents

| File | Purpose |
|------|---------|
| `agent.md` | Core instructions, coding patterns, and conventions for agents |
| `agent-pi.md` | Pi 5-specific agent instructions (Torque) |
| `agent.py` | Agent management CLI (getNext, list, sprint, clear) |
| `ralph_agents.json` | Tracks agent status and assignments |
| `progress.txt` | Logs agent progress and codebase patterns |
| `prompt.md` | The prompt template injected into each agent iteration |
| `ralph.sh` | Shell script to run agent iterations and coordinate assignment |
| `stories.json` | Current user stories (US- prefixed) for the active sprint |

## Quick Start

```bash
# Check sprint status without starting an agent
./ralph.sh status

# Run Ralph for 5 iterations
./ralph.sh 5

# Show help
./ralph.sh help
```

## Step-by-Step Usage

1. **Check Status** - Run `./ralph.sh status` to see agent assignments and sprint progress.

2. **Start Agent Iterations** - Use `./ralph.sh <iterations>` to launch an agent for N iterations. The script automatically assigns the next available agent.

3. **Agent Workflow** - Each iteration, the agent:
   - Reads `progress.txt` and `stories.json` to find the next task
   - Implements one user story following TDD methodology
   - Runs tests and quality checks
   - Commits changes and updates stories.json
   - Appends progress to `progress.txt`
   - Exits (ralph.sh starts the next iteration)

4. **Completion** - When all stories pass, the agent outputs `<promise>COMPLETE</promise>` and ralph.sh exits cleanly.

## Agent Management

```bash
# List all agents and their status
python ralph/agent.py list

# Show sprint progress (complete, blocked, available stories)
python ralph/agent.py sprint

# Get next available agent (used by ralph.sh internally)
python ralph/agent.py getNext

# Release a specific agent
python ralph/agent.py clear 1

# Release all agents
python ralph/agent.py clear all
```

## If ralph_agents.json Gets Broken or Out of Sync

**Symptoms**: Agents cannot be assigned, duplicate assignments, or errors in agent scripts.

**Fix Steps**:
1. **Manual Edit**: Open ralph_agents.json and ensure:
   - The `max_agent` value matches the number of active agent slots
   - Each agent object has a unique `id`, `name`, `type`, valid `status` ("unassigned" or "active"), and `taskid`
2. **Reset Status**: Run `python ralph/agent.py clear all` to reset all agents
3. **Validate JSON**: Use a JSON linter to check for syntax errors
4. **Test Assignment**: Run `python ralph/agent.py list` to confirm agents display correctly
5. **Backup**: Keep a backup of a working ralph_agents.json for quick recovery

## Tips

- Always run scripts from the project root
- Follow coding patterns in agent.md for consistency
- Check progress.txt for reusable patterns and gotchas before starting work
- If agent assignment fails, check ralph_agents.json first
- Use `./ralph.sh status` between runs to monitor progress
