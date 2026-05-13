#!/usr/bin/env bash
# ralph.sh — supervisor loop for the headless Ralph agent.
#
# ── Loop-control contract (rewritten 2026-05-12) ─────────────────────────────
# The continue/stop decision is derived from sprint.json state, NOT from the
# model's <promise> tag. The tag is advisory only:
#
#   * sprint.json shows every story passes:true ............ DONE        exit 0
#   * model emits <promise>HUMAN_INTERVENTION_REQUIRED</> .. stop        exit 0
#   * model emits <promise>SPRINT_BLOCKED</> .............. stop        exit 1
#   * an iteration exceeds ITERATION_TIMEOUT_SECONDS, or `claude`
#     exits non-zero ..................... handle_stuck_iteration() decides
#   * N consecutive iterations make NO progress (no story flips to
#     passes:true AND no new BL-*.md filed) ............... STALLED     exit 2
#   * anything else — including <promise>SPRINT_IN_PROGRESS</>,
#     <promise>ALL_BLOCKED</>, <promise>COMPLETE</> when the count
#     disagrees, or no tag at all ........................ CONTINUE
#
# SPRINT_IN_PROGRESS and ALL_BLOCKED are deliberately ignored: they assert
# cross-agent coordination that does not exist in a single-agent run, and
# honoring them is what used to stall the sprint mid-flight and force the CIO
# to babysit the harness. (Authoritative tag list still documented in
# prompt.md §Stop Condition — Ralph keeps emitting them, the harness just
# stops trusting them for loop control.)
#
# Robustness baked in here: each iteration runs under `timeout`; the assigned
# agent is ALWAYS released via an EXIT trap (Ctrl-C included); claude's full
# output is streamed live AND captured to offices/ralph/.last-iteration.log so
# a wedged iteration is post-mortem-able.

# Deliberately NOT `set -e`: this is a supervisor loop. A non-zero exit from
# `claude` (rate limit, context overflow, the `timeout` kill) is an expected,
# recoverable event — not a reason to kill the whole run before the cleanup
# trap and the next iteration get a chance to run.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BLOCKERS_DIR="$PROJECT_ROOT/offices/pm/blockers"
ITER_LOG="$SCRIPT_DIR/.last-iteration.log"

# Change to project root so Claude can access src/, tests/, specs/, etc.
cd "$PROJECT_ROOT"

# ── Loop-health policy ───────────────────────────────────────────────────────
# A legitimate M-sized story iteration runs roughly 15–30 min of wall clock
# (write failing test, implement, pytest, ruff, sprint_lint). Past this ceiling
# the iteration is wedged — kill it and let the policy hook decide what's next.
ITERATION_TIMEOUT_SECONDS=2700        # 45 min hard cap per `claude -p` call

# How many consecutive wedged iterations (timeout or crash) before aborting the
# whole run. 1 transient blip is worth a retry; a pattern is not.
MAX_STUCK_IN_A_ROW=2

# How many consecutive no-progress iterations before aborting. Catches the
# "agent keeps finishing but never advances the sprint" stall (distinct from a
# clean blocker, which stops immediately above).
MAX_NO_PROGRESS_IN_A_ROW=2

# --allowedTools: explicit auto-approval list for Bash commands in headless
# (-p) sessions. --permission-mode acceptEdits auto-accepts Edit/Write but NOT
# Bash, so this list must cover everything Ralph runs unattended.
#
# NOTE: ssh/scp/rsync/ssh-copy-id/ssh-keygen are included for the Pi-deploy
# stories (Sprint 10 "Pi Crawl"). They are also the prime suspects for the
# "sits for hours" hangs: an ssh to a powered-off Pi, or a first-connect
# host-key prompt, blocks on stdin forever. If .last-iteration.log confirms
# that, either (a) add a `Host chi-eclipse-01` block to ~/.ssh/config with
# `BatchMode yes` + `ConnectTimeout 15`, or (b) switch RALPH_ALLOWED_TOOLS to
# the RALPH_ALLOWED_TOOLS_NO_SSH line below — live-Pi access is a CIO follow-up
# per recent sprint notes, not something Ralph should do unattended anyway.
RALPH_ALLOWED_TOOLS="Bash(git:*),Bash(python:*),Bash(python3:*),Bash(pytest:*),Bash(pip:*),Bash(ssh:*),Bash(scp:*),Bash(rsync:*),Bash(ssh-copy-id:*),Bash(ssh-keygen:*),Bash(bash:*),Bash(sh:*),Bash(make:*),Bash(ruff:*),Bash(black:*),Bash(mypy:*),Bash(grep:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(find:*),Bash(wc:*),Bash(sort:*),Bash(uniq:*),Bash(diff:*),Bash(sed:*),Bash(awk:*),Bash(mkdir:*),Bash(cp:*),Bash(mv:*),Bash(rm:*),Bash(echo:*),Bash(printf:*),Bash(date:*),Bash(touch:*),Bash(test:*),Bash(true:*),Bash(false:*),Bash(timeout:*),Bash(cd:*),Bash(which:*),Bash(realpath:*),Bash(basename:*),Bash(dirname:*),Bash(xargs:*),Bash(tr:*),Bash(env:*)"
# RALPH_ALLOWED_TOOLS_NO_SSH="$(printf '%s' "$RALPH_ALLOWED_TOOLS" | sed 's/Bash(ssh:\*),Bash(scp:\*),Bash(rsync:\*),Bash(ssh-copy-id:\*),Bash(ssh-keygen:\*),//')"

# Never let git or pip block the loop on an interactive prompt; keep the
# streamed transcript live (no Python stdout buffering).
export GIT_TERMINAL_PROMPT=0
export PYTHONUNBUFFERED=1

# ── Always release the assigned agent, however the script exits ──────────────
_cleanup_done=0
cleanup() {
  [ "$_cleanup_done" = "1" ] && return 0
  _cleanup_done=1
  if [ -n "${FIRST_UNASSIGNED_AGENT:-}" ] && \
     printf '%s' "${FIRST_UNASSIGNED_AGENT:-}" | grep -Eq '^[1-9][0-9]*$'; then
    python "$SCRIPT_DIR/agent.py" clear "$FIRST_UNASSIGNED_AGENT" >/dev/null 2>&1 || true
    echo ""
    echo "[ralph.sh] released agent #$FIRST_UNASSIGNED_AGENT"
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# ── Authoritative story tally, straight from sprint.json ─────────────────────
# Mirrors agent.py: a story counts complete only when `passes` is the boolean
# True. Prints "<complete> <total>"; always two ints, even on a broken file.
story_counts() {
  python - "$SCRIPT_DIR/sprint.json" <<'PY'
import json, sys
try:
    stories = json.load(open(sys.argv[1], encoding="utf-8")).get("stories", [])
except Exception:
    print("0 0"); raise SystemExit(0)
print(sum(1 for s in stories if s.get("passes") is True), len(stories))
PY
}

# ── handle_stuck_iteration ───────────────────────────────────────────────────
# Called when an iteration wedged: `claude` was killed by `timeout` (rc 124) or
# exited non-zero for some other reason. You decide whether to shrug it off and
# let the loop try again, or abort the whole run for a human to look at.
#
#   $1  rc           — claude's exit code (124 == hit ITERATION_TIMEOUT_SECONDS)
#   $2  stuck_streak — how many iterations IN A ROW have now wedged (1 == first)
#
#   return 0  -> recoverable; ralph.sh continues to the next iteration
#   return 1  -> give up; ralph.sh stops the run (exit 2)
#
# Default below is the obvious one: retry until MAX_STUCK_IN_A_ROW, then abort.
# It works as-is. Worth customizing if your domain knowledge says otherwise —
# e.g. treat rc 124 (timeout) and other non-zero codes differently, add a short
# backoff `sleep` before the retry, or drop a heads-up note into
# offices/pm/inbox/ on abort so the PM sees it next session.
handle_stuck_iteration() {
  local rc="$1" stuck_streak="$2"
  if [ "$stuck_streak" -lt "$MAX_STUCK_IN_A_ROW" ]; then
    return 0
  fi
  return 1
}

# ── CLI ──────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "status" ]; then
  echo "=== Ralph Sprint Status ==="
  echo ""
  python "$SCRIPT_DIR/agent.py" list
  echo ""
  python "$SCRIPT_DIR/agent.py" sprint
  exit 0
fi

if [ "${1:-}" = "help" ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Usage: $0 <iterations|command>"
  echo ""
  echo "Commands:"
  echo "  <number>   Run agent for up to N iterations (e.g., ./ralph.sh 10)"
  echo "  status     Show agent and sprint status without starting an agent"
  echo "  help       Show this help message"
  echo ""
  echo "The loop runs until the sprint is complete, a blocker stops it, an"
  echo "iteration wedges past ${ITERATION_TIMEOUT_SECONDS}s too many times, the"
  echo "sprint stalls, or it has used all N iterations — whichever comes first."
  echo "It does NOT stop just because the model emitted a coordination tag."
  echo ""
  echo "Examples:"
  echo "  ./ralph.sh 10      Run up to 10 iterations"
  echo "  ./ralph.sh status  Check sprint progress"
  exit 0
fi

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <iterations>"
  echo "       $0 status     (show sprint status)"
  echo "       $0 help       (show help)"
  exit 1
fi

if ! [[ "$1" =~ ^[0-9]+$ ]]; then
  echo "Error: iterations must be a number, got '$1'"
  echo "Use './ralph.sh help' for usage"
  exit 1
fi

# Load the per-iteration headless contract.
PROMPT=$(<"$SCRIPT_DIR/prompt.md")

# Claim the first unassigned agent.
FIRST_UNASSIGNED_AGENT=$(python "$SCRIPT_DIR/agent.py" getNext)
if [ "$FIRST_UNASSIGNED_AGENT" -eq 0 ]; then
  FIRST_UNASSIGNED_AGENT=""   # nothing to release in the cleanup trap
  echo "No unassigned agent found — all agents are marked active."
  echo "If a previous run crashed and left one stranded, reset with:"
  echo "    python offices/ralph/agent.py clear all"
  echo "Rainbows taste great"
  exit 0
fi
PROMPT="Your Agent_ID = $FIRST_UNASSIGNED_AGENT"$'\n'"$PROMPT"
echo "Ralph agent #$FIRST_UNASSIGNED_AGENT reporting for duty."

stuck_streak=0
no_progress_streak=0

for ((i=1; i<=$1; i++)); do
  echo ""
  echo "=============================================="
  echo "Agent: $FIRST_UNASSIGNED_AGENT | Iteration $i of $1"
  echo "=============================================="
  read -r before_complete total < <(story_counts)
  echo "Sprint progress: $before_complete / $total stories complete"
  echo "----------------------------------------------"

  # Marker file: its mtime is "now", so `find -newer` afterwards finds any
  # BL-*.md this iteration filed (and ignores ones from earlier runs).
  marker="$(mktemp)"

  # Run one iteration: hard wall-clock cap, full transcript streamed live and
  # captured to ITER_LOG for post-mortem if it wedges.
  timeout -k 30 "$ITERATION_TIMEOUT_SECONDS" \
    claude --allowedTools "$RALPH_ALLOWED_TOOLS" --permission-mode acceptEdits \
      -p "@offices/ralph/sprint.json @offices/ralph/progress.txt @offices/ralph/agent.md $PROMPT " \
    2>&1 | tee "$ITER_LOG"
  rc=${PIPESTATUS[0]}

  read -r after_complete total < <(story_counts)
  new_blocker="$(find "$BLOCKERS_DIR" -maxdepth 1 -name 'BL-*.md' -newer "$marker" 2>/dev/null | head -n 1)"
  rm -f "$marker"

  echo ""
  echo "--- Iteration $i complete (claude exit $rc) — Sprint progress: $after_complete / $total ---"

  # 1. Sprint actually finished? sprint.json is the authority — no tag needed.
  if [ "$total" -gt 0 ] && [ "$after_complete" -ge "$total" ]; then
    echo ""
    echo "*** PRD COMPLETE — all $total stories pass. ***"
    exit 0
  fi

  # 2. Iteration wedged (timeout or crash)? Hand to the policy hook.
  if [ "$rc" -ne 0 ]; then
    stuck_streak=$((stuck_streak + 1))
    if [ "$rc" -eq 124 ]; then
      echo "!! Iteration $i exceeded ${ITERATION_TIMEOUT_SECONDS}s and was killed (stuck streak: $stuck_streak)."
    else
      echo "!! claude exited $rc on iteration $i (stuck streak: $stuck_streak)."
    fi
    echo "   Transcript: $ITER_LOG"
    if handle_stuck_iteration "$rc" "$stuck_streak"; then
      echo "   -> retrying (this consumes one of the $1 iterations)."
      continue
    fi
    echo ""
    echo "*** ABORTING — iteration wedged and handle_stuck_iteration() said stop. ***"
    echo "    Inspect $ITER_LOG; re-run './ralph.sh N' once the cause is cleared."
    exit 2
  fi
  stuck_streak=0

  # 3. Honor a real blocker signal. These tags are advisory, but they're the
  #    one class of "stop now" the model is allowed to assert in single-agent
  #    mode, and the contract requires a BL-*.md to back them.
  if grep -q '<promise>HUMAN_INTERVENTION_REQUIRED</promise>' "$ITER_LOG"; then
    echo ""
    echo "*** HUMAN INTERVENTION REQUIRED — see offices/pm/blockers/ ***"
    exit 0
  fi
  if grep -q '<promise>SPRINT_BLOCKED</promise>' "$ITER_LOG"; then
    echo ""
    echo "*** SPRINT BLOCKED — all remaining work is blocked; PM action required."
    echo "    See offices/pm/blockers/ ***"
    exit 1
  fi

  # 4. Did this iteration make progress? A flipped story OR a freshly-filed
  #    blocker counts. If not, and it keeps not counting, stop — don't sit.
  if [ "$after_complete" -gt "$before_complete" ] || [ -n "$new_blocker" ]; then
    no_progress_streak=0
  else
    no_progress_streak=$((no_progress_streak + 1))
    echo "   (no story completed and no new blocker filed — no-progress streak: $no_progress_streak)"
    if [ "$no_progress_streak" -ge "$MAX_NO_PROGRESS_IN_A_ROW" ]; then
      echo ""
      echo "*** STALLED — $no_progress_streak iterations advanced nothing and filed no blocker. Stopping. ***"
      echo "    Inspect $ITER_LOG to see what the agent did instead."
      exit 2
    fi
  fi

  # 5. Otherwise: SPRINT_IN_PROGRESS / ALL_BLOCKED / PARTIAL_BLOCKED / no tag —
  #    keep going. Note (don't obey) a misfired coordination tag.
  if grep -q '<promise>SPRINT_IN_PROGRESS</promise>\|<promise>ALL_BLOCKED</promise>' "$ITER_LOG"; then
    echo "   (model emitted a multi-agent coordination tag in a single-agent run — ignoring it, continuing.)"
  fi
done

echo ""
echo "=============================================="
echo "Ralph agent #$FIRST_UNASSIGNED_AGENT used all $1 iteration(s)."
echo "=============================================="
read -r final_complete total < <(story_counts)
echo "Final sprint progress: $final_complete / $total stories complete"
if [ "$total" -gt 0 ] && [ "$final_complete" -lt "$total" ]; then
  echo ""
  echo "Work remaining. './ralph.sh status' for details; './ralph.sh N' to keep going."
fi
exit 0
