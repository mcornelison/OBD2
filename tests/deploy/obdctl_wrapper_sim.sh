#!/usr/bin/env bash
################################################################################
# File Name: obdctl_wrapper_sim.sh
# Purpose/Description: US-492 [F-122] harness that executes deploy-pi.sh's
#   step_install_obdctl OFF the Pi, with `remote` captured and `sudo` stubbed,
#   so the wrapper the deploy would actually write can be inspected + run.
#   Static assertions on the step body cannot catch a mis-escaped heredoc; this
#   runs it. Driven by tests/deploy/test_obdctl_install.py.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial implementation (US-492 obdctl).
# ================================================================================
################################################################################
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# `sudo` stub: run the command as-is, so `install`/`cmp`/`test` land in WORK_DIR.
mkdir -p "$WORK_DIR/bin"
printf '#!/bin/sh\nexec "$@"\n' > "$WORK_DIR/bin/sudo"
chmod +x "$WORK_DIR/bin/sudo"
PATH="$WORK_DIR/bin:$PATH"

# The step reads these from deploy-pi.sh's global scope.
PI_PATH="$WORK_DIR/pi"
DRY_RUN=false

# `remote` normally SSHes; here it runs the same string in a local shell, which
# is what makes a quoting/escaping bug in the heredoc actually fail.
remote() { bash -c "$1"; }

# Pull ONLY the step out of deploy-pi.sh (sourcing the whole script would run a
# deploy). The function is self-contained by design.
eval "$(sed -n '/^step_install_obdctl() {/,/^}$/p' "$REPO_ROOT/deploy/deploy-pi.sh")"

# The step installs to an absolute /usr/local/bin path; redirect that by running
# it against a shimmed root. `install` needs the parent dir to exist.
mkdir -p "$WORK_DIR/usr/local/bin" "$PI_PATH/src/pi/ops"
cp "$REPO_ROOT/src/pi/ops/obdctl.py" "$PI_PATH/src/pi/ops/obdctl.py"
cp "$REPO_ROOT/src/pi/ops/unit_manifest.py" "$PI_PATH/src/pi/ops/unit_manifest.py"
touch "$PI_PATH/src/pi/ops/__init__.py"
mkdir -p "$PI_PATH/src/pi"
touch "$PI_PATH/src/pi/__init__.py"

# Run the real step body with the absolute target rewritten into WORK_DIR.
stepBody="$(declare -f step_install_obdctl)"
eval "${stepBody//\/usr\/local\/bin\/obdctl/$WORK_DIR/usr/local/bin/obdctl}"
step_install_obdctl > "$WORK_DIR/step.log" 2>&1 || {
    echo "STEP FAILED"; cat "$WORK_DIR/step.log"; exit 1
}

WRAPPER="$WORK_DIR/usr/local/bin/obdctl"
[ -x "$WRAPPER" ] || { echo "FAIL: wrapper not installed/executable"; exit 1; }

echo "--- generated wrapper ---"
cat "$WRAPPER"
echo "--- end wrapper ---"

# The load-bearing check: the wrapper the deploy writes must actually RUN.
# Substitute the local python for the Pi's /usr/bin/python3.
sed "s|/usr/bin/python3|$(command -v python3)|" "$WRAPPER" > "$WRAPPER.local"
chmod +x "$WRAPPER.local"
"$WRAPPER.local" --help > "$WORK_DIR/help.txt" 2>&1 || {
    echo "FAIL: wrapper did not run"; cat "$WORK_DIR/help.txt"; exit 1
}
grep -q "obdctl -- control the Eclipse OBD services" "$WORK_DIR/help.txt" || {
    echo "FAIL: wrapper ran but produced unexpected output"; cat "$WORK_DIR/help.txt"; exit 1
}

# Idempotence: a second run must report no change, not reinstall.
step_install_obdctl > "$WORK_DIR/step2.log" 2>&1
grep -q "already current" "$WORK_DIR/step2.log" || {
    echo "FAIL: step is not idempotent"; cat "$WORK_DIR/step2.log"; exit 1
}

echo "OBDCTL WRAPPER SIM: PASS"
