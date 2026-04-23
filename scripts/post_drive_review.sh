#!/usr/bin/env bash
################################################################################
# post_drive_review.sh -- Wire the post-drive review ritual (US-219).
#
# Orchestrates the four steps a CIO runs after any real drive:
#
#   1. Numeric drive report         (scripts/report.py --drive-id N)
#   2. Spool AI prompt invocation   (scripts/spool_prompt_invoke.py)
#   3. Drive review checklist       (offices/tuner/drive-review-checklist.md)
#   4. "Where to log findings" pointer
#
# This script WIRES already-shipped pieces -- it does not implement analysis
# or mutate data.  Ollama offline is non-fatal (step 2 prints an advisory and
# exits 0).  Missing drive data is non-fatal (empty-array response is valid).
#
# Usage:
#   bash scripts/post_drive_review.sh                       # latest drive
#   bash scripts/post_drive_review.sh --drive-id 5          # drive_summary.id=5
#   bash scripts/post_drive_review.sh --drive-id latest     # same as default
#   bash scripts/post_drive_review.sh --dry-run             # skip Ollama call
#   bash scripts/post_drive_review.sh --help
#
# Exit codes:
#   0  -- every step emitted (normal path OR graceful no-data / Ollama offline)
#   2  -- argument error (bad flag, missing value)
################################################################################

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DRIVE_ID="latest"
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: bash scripts/post_drive_review.sh [--drive-id N|latest] [--dry-run] [--help]

Post-drive review ritual (US-219).  Runs four steps against the current
server database:

  1. Numeric drive report (scripts/report.py --drive-id N)
  2. Spool AI prompt + Ollama response (scripts/spool_prompt_invoke.py)
  3. Drive review checklist (offices/tuner/drive-review-checklist.md)
  4. "Where to record findings" pointer

Flags:
  --drive-id N      Target drive_summary.id (integer) OR 'latest' (default).
  --dry-run         Pass through to step 2 to skip the actual Ollama call.
  -h, --help        Print this help and exit.

Exit codes:
  0   All steps emitted.  Empty drive / Ollama offline are non-fatal.
  2   Argument parsing failed.

Example:
  bash scripts/post_drive_review.sh --drive-id 17 | tee review-17.txt
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --drive-id)
            if [[ $# -lt 2 ]]; then
                echo "Error: --drive-id requires a value (integer or 'latest')" >&2
                exit 2
            fi
            DRIVE_ID="$2"
            shift 2
            ;;
        --drive-id=*)
            DRIVE_ID="${1#--drive-id=}"
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown flag: $1" >&2
            echo "Run 'bash scripts/post_drive_review.sh --help' for usage." >&2
            exit 2
            ;;
    esac
done

# Resolve the Python interpreter: prefer an active venv, fall back to 'python'.
if [[ -n "${VIRTUAL_ENV:-}" ]] && [[ -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
else
    PYTHON_BIN="${POST_DRIVE_REVIEW_PYTHON:-python}"
fi

CHECKLIST_PATH="$REPO_ROOT/offices/tuner/drive-review-checklist.md"

print_header() {
    local num="$1" title="$2"
    echo ""
    echo "════════════════════════════════════════════════════════════════════════"
    echo "  Step $num / 4 -- $title"
    echo "════════════════════════════════════════════════════════════════════════"
}

cd "$REPO_ROOT"

# ---- Step 1: numeric drive report --------------------------------------------
print_header 1 "Numeric drive report"
if ! "$PYTHON_BIN" scripts/report.py --drive-id "$DRIVE_ID"; then
    echo ""
    echo "  (report.py exited non-zero -- continuing with remaining steps)"
fi

# ---- Step 2: Spool AI prompt + Ollama ----------------------------------------
print_header 2 "Spool AI prompt + Ollama response"
SPOOL_ARGS=(--drive-id "$DRIVE_ID")
if [[ "$DRY_RUN" -eq 1 ]]; then
    SPOOL_ARGS+=(--dry-run)
fi
"$PYTHON_BIN" scripts/spool_prompt_invoke.py "${SPOOL_ARGS[@]}" || {
    rc=$?
    echo ""
    echo "  (spool_prompt_invoke.py exited $rc -- continuing)"
}

# ---- Step 3: drive review checklist ------------------------------------------
print_header 3 "Drive review checklist (Spool)"
if [[ -f "$CHECKLIST_PATH" ]]; then
    cat "$CHECKLIST_PATH"
else
    echo "  Checklist not found at $CHECKLIST_PATH"
    echo "  Inbox Spool at offices/tuner/inbox/ to provide one."
fi

# ---- Step 4: where to record findings ----------------------------------------
TODAY="$(date +%Y-%m-%d)"
print_header 4 "Record your findings"
cat <<EOF

  Spool review note (recommended):
    offices/tuner/reviews/drive-${DRIVE_ID}-review.md

  OR send findings to Marcus via inbox note:
    offices/pm/inbox/${TODAY}-from-spool-drive-${DRIVE_ID}-review.md

  Template for the inbox note is the Section G format in the checklist
  above (overall grade / pipeline / idle / warmup / drive / red flags /
  data quality / change requests / open questions).

  Review complete.

EOF
