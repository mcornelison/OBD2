set -e

# Promise-tag contract:
# The authoritative list of <promise>TAG</promise> tokens this script branches on
# lives in offices/ralph/prompt.md §Stop Condition. Keep the two lists in sync.
# Behavior: SPRINT_BLOCKED exits 1; all other stop tags exit 0; PARTIAL_BLOCKED
# continues the loop; no tag continues the loop.

# Get the directory where this script is located (offices/ralph/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Project root is two levels up from offices/ralph/
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Change to project root so Claude can access src/, tests/, specs/, etc.
cd "$PROJECT_ROOT"

# Handle 'status' command - quick sprint check without starting an agent
if [ "$1" = "status" ]; then
  echo "=== Ralph Sprint Status ==="
  echo ""
  python "$SCRIPT_DIR/agent.py" list
  echo ""
  python "$SCRIPT_DIR/agent.py" sprint
  exit 0
fi

# Handle 'help' command
if [ "$1" = "help" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  echo "Usage: $0 <iterations|command>"
  echo ""
  echo "Commands:"
  echo "  <number>   Run agent for N iterations (e.g., ./ralph.sh 5)"
  echo "  status     Show agent and sprint status without starting an agent"
  echo "  help       Show this help message"
  echo ""
  echo "Examples:"
  echo "  ./ralph.sh 10      Run 10 iterations"
  echo "  ./ralph.sh status  Check sprint progress"
  exit 0
fi

if [ -z "$1" ]; then
  echo "Usage: $0 <iterations>"
  echo "       $0 status     (show sprint status)"
  echo "       $0 help       (show help)"
  exit 1
fi

# Validate iterations is a number
if ! [[ "$1" =~ ^[0-9]+$ ]]; then
  echo "Error: iterations must be a number, got '$1'"
  echo "Use './ralph.sh help' for usage"
  exit 1
fi

# Load the prompt from the prompt.md file
PROMPT=$(<"$SCRIPT_DIR/prompt.md")

# Find first unassigned agent from ralph_agents.json
FIRST_UNASSIGNED_AGENT=$(python "$SCRIPT_DIR/agent.py" getNext)
if [ "$FIRST_UNASSIGNED_AGENT" -eq 0 ]; then
  echo "No unassigned agent found."
  echo "Rainbows taste great"
  exit 0
fi

PROMPT="Your Agent_ID = $FIRST_UNASSIGNED_AGENT"$'\n'"$PROMPT"
echo "Ralph agent #$FIRST_UNASSIGNED_AGENT reporting for duty."

for ((i=1; i<=$1; i++)); do
  echo ""
  echo "=============================================="
  echo "Agent: $FIRST_UNASSIGNED_AGENT | Iteration $i of $1"
  echo "=============================================="

  # Show sprint progress before each iteration
  STORIES_COMPLETE=$(grep -c '"passes": true' offices/ralph/sprint.json 2>/dev/null || echo 0)
  STORIES_TOTAL=$(grep -c '"id": "US-' offices/ralph/sprint.json 2>/dev/null || echo 0)
  echo "Sprint progress: $STORIES_COMPLETE / $STORIES_TOTAL stories complete"
  echo "----------------------------------------------"

  # --allowedTools: explicit auto-approval list for Bash commands during
  # non-interactive sessions. --permission-mode acceptEdits auto-accepts
  # Edit/Write operations but NOT Bash — so this list must cover every
  # command Ralph needs to run unattended. Sprint 10 (Pi Crawl) added
  # ssh/rsync/scp/bash for the Pi deploy path; other quality and utility
  # tools added for general TDD work.
  RALPH_ALLOWED_TOOLS="Bash(git:*),Bash(python:*),Bash(python3:*),Bash(pytest:*),Bash(pip:*),Bash(ssh:*),Bash(scp:*),Bash(rsync:*),Bash(ssh-copy-id:*),Bash(ssh-keygen:*),Bash(bash:*),Bash(sh:*),Bash(make:*),Bash(ruff:*),Bash(black:*),Bash(mypy:*),Bash(grep:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(find:*),Bash(wc:*),Bash(sort:*),Bash(uniq:*),Bash(diff:*),Bash(sed:*),Bash(awk:*),Bash(mkdir:*),Bash(cp:*),Bash(mv:*),Bash(rm:*),Bash(echo:*),Bash(printf:*),Bash(date:*),Bash(touch:*),Bash(test:*),Bash(true:*),Bash(false:*),Bash(timeout:*),Bash(cd:*),Bash(which:*),Bash(realpath:*),Bash(basename:*),Bash(dirname:*),Bash(xargs:*),Bash(tr:*),Bash(env:*)"

  result=$(claude --allowedTools "$RALPH_ALLOWED_TOOLS" --permission-mode acceptEdits -p "@offices/ralph/sprint.json @offices/ralph/progress.txt @offices/ralph/agent.md $PROMPT ")

  echo "$result"

  # Show updated progress after iteration
  echo ""
  echo "--- Iteration $i Complete ---"
  STORIES_COMPLETE=$(grep -c '"passes": true' offices/ralph/sprint.json 2>/dev/null || echo 0)
  echo "Sprint progress: $STORIES_COMPLETE / $STORIES_TOTAL stories complete"

  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo ""
    echo "*** PRD COMPLETE - All stories passed! ***"
    (python "$SCRIPT_DIR/agent.py" clear "$FIRST_UNASSIGNED_AGENT")
    exit 0
  fi
  if [[ "$result" == *"<promise>HUMAN_INTERVENTION_REQUIRED</promise>"* ]]; then
    echo ""
    echo "*** HUMAN INTERVENTION REQUIRED - Check pm/blockers/ ***"
    (python "$SCRIPT_DIR/agent.py" clear "$FIRST_UNASSIGNED_AGENT")
    exit 0
  fi
  if [[ "$result" == *"<promise>SPRINT_IN_PROGRESS</promise>"* ]]; then
    echo ""
    echo "*** Agent done - other agents still working ***"
    (python "$SCRIPT_DIR/agent.py" clear "$FIRST_UNASSIGNED_AGENT")
    exit 0
  fi
  if [[ "$result" == *"<promise>ALL_BLOCKED</promise>"* ]]; then
    echo ""
    echo "*** No work available - tasks blocked by other agents ***"
    (python "$SCRIPT_DIR/agent.py" clear "$FIRST_UNASSIGNED_AGENT")
    exit 0
  fi
  if [[ "$result" == *"<promise>PARTIAL_BLOCKED</promise>"* ]]; then
    echo ""
    echo "*** Some stories blocked, but work remains ***"
    echo "Check pm/blockers/ for blocker details"
    echo "Continuing to next iteration..."
    # Don't exit - continue to next iteration
  fi
  if [[ "$result" == *"<promise>SPRINT_BLOCKED</promise>"* ]]; then
    echo ""
    echo "*** SPRINT BLOCKED - All remaining tasks are blocked/unresolvable ***"
    echo "Check pm/blockers/ for details. PM action required."
    (python "$SCRIPT_DIR/agent.py" clear "$FIRST_UNASSIGNED_AGENT")
    exit 1
  fi

done
(python "$SCRIPT_DIR/agent.py" clear "$FIRST_UNASSIGNED_AGENT")
echo ""
echo "=============================================="
echo "Ralph agent #$FIRST_UNASSIGNED_AGENT completed $1 iteration(s)"
echo "=============================================="
STORIES_COMPLETE=$(grep -c '"passes": true' offices/ralph/sprint.json 2>/dev/null || echo 0)
STORIES_TOTAL=$(grep -c '"id": "US-' offices/ralph/sprint.json 2>/dev/null || echo 0)
echo "Final sprint progress: $STORIES_COMPLETE / $STORIES_TOTAL stories complete"
if [ "$STORIES_COMPLETE" -lt "$STORIES_TOTAL" ]; then
  echo ""
  echo "Work remaining. Run './ralph.sh status' to see details."
  echo "Run './ralph.sh N' to continue (N = number of iterations)."
fi
