"""Run-not-trust deploy pre-flight test gate for /sprint-deploy-pm Phase 0.

Pays down US-469 (SS-T7 deploy-gate tripwire / F-118). Closes the
best-effort-continue-past-red class of deploy bug that shipped broken twice:

* **V0.27.12 DOA (the SS-T7 lesson).** The systemd-parity tripwire test
  (`tests/pi/power/power_watch/test_systemd_parity.py`) *existed* but the deploy
  pipeline never RAN it, so a systemd-unit drift shipped dead-on-arrival.
* **V0.27.17 marker-on-failure.** A deploy step treated an `exit 0` as success
  and wrote a green *marker* even when the underlying job logged 10/10 FAILED --
  a red gate passed with a green marker.

Both failures share one root cause: the pipeline trusted a green *signal* (a
marker file, or "the test exists") instead of observing a green *result*. This
gate replaces trust with execution. It ACTUALLY invokes `pytest -m "not slow"`
(the suite that contains the SS-T7 tripwire) and reports PASS only when it just
watched that run exit 0. There is deliberately NO code path -- no marker read, no
"prior report" / "Ralph said green" flag, no skip hatch -- that lets a caller
bypass the run. On any non-zero pytest exit the gate HALTs the deploy; if pytest
cannot even be launched the gate fails SAFE (also HALT): uncertainty must never
authorize a deploy (mirrors the retry-defaults-to-uncertain discipline).

Usage (CLI -- wired as the first HALT-early gate of /sprint-deploy-pm Phase 0):

    python -m tools.pm.deploy_preflight_gate --repo .

Exit code 0 = suite green, deploy may proceed; non-zero (HALT_EXIT_CODE) = a red
gate or an un-launchable pytest -- HALT the deploy and investigate. `--marker`
and target paths tune WHAT is run (used by tests), never WHETHER it runs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# The suite that MUST run before a deploy: everything except the `slow` marker.
# This is the suite that contains the SS-T7 systemd-parity DOA tripwire.
DEFAULT_MARKER_EXPR = "not slow"

# Non-zero CLI exit that signals "HALT the deploy" to the calling shell (Phase 0).
HALT_EXIT_CODE = 2


class GateOutcome(Enum):
    """The verdict of a pre-flight test-gate run."""

    PASS = "pass"  # pytest exited 0 -- the deploy may proceed
    HALT = "halt"  # pytest exited non-zero -- a red gate; block the deploy
    ERROR = "error"  # pytest could not be launched -- fail safe (block the deploy)


# Only a green run authorizes a deploy; HALT (red) and ERROR (un-launchable) both
# block. ERROR is deliberately NOT proceedable -- an undetectable state must never
# read as success (the V0.27.17 marker-on-failure trap in reverse).
_PROCEED_OUTCOMES = frozenset({GateOutcome.PASS})


@dataclass(frozen=True)
class GateResult:
    """The outcome of a pre-flight test-gate run.

    Attributes:
        outcome: The `GateOutcome` reached.
        returnCode: The pytest process exit code, or None if it never launched.
        argv: The exact pytest argv that was (or would have been) run.
        message: A human-readable one-line summary.
    """

    outcome: GateOutcome
    returnCode: int | None
    argv: list[str]
    message: str

    @property
    def deployMayProceed(self) -> bool:
        """True only when the pre-flight suite ran green (PASS)."""
        return self.outcome in _PROCEED_OUTCOMES


def buildPytestArgv(
    *,
    markerExpr: str = DEFAULT_MARKER_EXPR,
    targetPaths: tuple[str, ...] = (),
    pythonExe: str | None = None,
) -> list[str]:
    """Build the `python -m pytest -m <markerExpr> [targets...]` argv.

    Args:
        markerExpr: The pytest `-m` marker expression to select (default
            ``"not slow"`` -- the SS-T7-bearing suite).
        targetPaths: Optional explicit paths to restrict collection to (used by
            tests to point at a throwaway suite); empty = the whole repo suite.
        pythonExe: The interpreter to invoke pytest with; defaults to the current
            `sys.executable` so the gate uses the PM's active venv.

    Returns:
        The argv list to hand to a runner.
    """
    argv = [pythonExe or sys.executable, "-m", "pytest", "-m", markerExpr]
    argv.extend(targetPaths)
    return argv


def _defaultRunner(argv: list[str], cwd: Path | str) -> int:
    """Run pytest as a real subprocess, streaming output, and return its exit code.

    Output is intentionally NOT captured so the PM sees the live pytest run in the
    deploy log (run-not-trust: the evidence is on screen).

    Args:
        argv: The pytest argv (from `buildPytestArgv`).
        cwd: The working directory to launch pytest in (the repo root).

    Returns:
        The pytest process return code.

    Raises:
        OSError / subprocess.SubprocessError: if pytest cannot be launched; the
            caller catches this and fails safe to ERROR/HALT.
    """
    completed = subprocess.run(argv, cwd=str(cwd), check=False)
    return completed.returncode


def runPreflightGate(
    repoRoot: Path | str,
    *,
    markerExpr: str = DEFAULT_MARKER_EXPR,
    targetPaths: tuple[str, ...] = (),
    runner=None,
) -> GateResult:
    """RUN the pre-flight pytest suite and return a proceed/HALT verdict.

    This is the run-not-trust gate: it always invokes the runner (there is no
    marker read and no "trust a prior report" path). A non-zero pytest exit HALTs
    the deploy; a runner that cannot launch pytest fails safe to ERROR (also a
    block).

    Args:
        repoRoot: The working-tree root; pytest is launched with this as cwd.
        markerExpr: The pytest marker expression (default ``"not slow"``).
        targetPaths: Optional explicit collection paths (tests only; empty = the
            whole suite).
        runner: A callable ``(argv, cwd) -> int`` returning the pytest exit code
            (injectable for tests); defaults to a real subprocess run.

    Returns:
        A `GateResult`. `deployMayProceed` is True ONLY for a green (PASS) run.
    """
    argv = buildPytestArgv(markerExpr=markerExpr, targetPaths=targetPaths)
    run = runner or _defaultRunner
    try:
        returnCode = run(argv, repoRoot)
    except (OSError, subprocess.SubprocessError) as exc:
        return GateResult(
            GateOutcome.ERROR,
            None,
            argv,
            f"HALT: could not launch pytest ({exc}); failing safe -- deploy blocked",
        )

    if returnCode == 0:
        return GateResult(
            GateOutcome.PASS,
            returnCode,
            argv,
            f"PASS: pre-flight suite (pytest -m '{markerExpr}') is green -- deploy may proceed",
        )
    return GateResult(
        GateOutcome.HALT,
        returnCode,
        argv,
        f"HALT: pre-flight suite (pytest -m '{markerExpr}') exited {returnCode} -- deploy blocked",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: RUN the not-slow suite and gate the deploy on the result.

    Args:
        argv: Argument vector (defaults to `sys.argv[1:]`).

    Returns:
        0 when the suite ran green (deploy may proceed); `HALT_EXIT_CODE` (2) on a
        red suite or an un-launchable pytest (HALT the deploy).
    """
    parser = argparse.ArgumentParser(
        prog="deploy_preflight_gate",
        description=(
            "Run-not-trust deploy pre-flight gate: RUNS pytest -m 'not slow' and "
            "HALTs the deploy on any non-zero exit (US-469 / SS-T7)."
        ),
    )
    parser.add_argument("--repo", default=".", help="repo root to run pytest in (default: .)")
    parser.add_argument(
        "--marker",
        default=DEFAULT_MARKER_EXPR,
        help=f"pytest -m marker expression (default: {DEFAULT_MARKER_EXPR!r})",
    )
    args = parser.parse_args(argv)

    result = runPreflightGate(args.repo, markerExpr=args.marker)
    print(f"[deploy_preflight_gate] {result.message}")
    return 0 if result.deployMayProceed else HALT_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
