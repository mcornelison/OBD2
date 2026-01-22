set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <iterations>"
  exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root for claude commands
cd "$PROJECT_ROOT"

# Load the prompt from the prompt.md file
PROMPT=$(<"$SCRIPT_DIR/prompt.md")

# Find first unassigned agent from ralph_agents.txt
FIRST_UNASSIGNED_AGENT=$(python "$SCRIPT_DIR/get_next_agent.py")
if [ "$FIRST_UNASSIGNED_AGENT" -eq 0 ]; then
  echo "No unassigned agent found."
  echo "Rainbows taste great"
  exit 0
fi

PROMPT="Your Agent_ID = $FIRST_UNASSIGNED_AGENT"$'\n'"$PROMPT"
echo "Ralph agent #$FIRST_UNASSIGNED_AGENT reporting for duty."

for ((i=1; i<=$1; i++)); do
  echo "Agent: $FIRST_UNASSIGNED_AGENT | Iteration $i"
  echo "-----------------------------" 
  
  result=$(claude  --allowedTools "Bash(git:*),Bash(python:*),Bash(pytest:*)" --permission-mode acceptEdits -p "@ralph/prd.json @ralph/progress.txt @ralph/AGENT.md $PROMPT ")

  echo "$result"

  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo "PRD complete, exiting."
    (python "$SCRIPT_DIR/set_agent_free.py" "$FIRST_UNASSIGNED_AGENT")
    exit 0
  fi
  if [[ "$result" == *"<promise>HUMAN_INTERVENTION_REQUIRED</promise>"* ]]; then
    echo "Human intervention required, exiting."
    (python "$SCRIPT_DIR/set_agent_free.py" "$FIRST_UNASSIGNED_AGENT")
    exit 0
  fi

done
(python "$SCRIPT_DIR/set_agent_free.py" "$FIRST_UNASSIGNED_AGENT")
echo "Ralph agent #$FIRST_UNASSIGNED_AGENT is now free."
