################################################################################
# File Name: test_deploy_server_backfill_drives_11_20.py
# Purpose/Description: Static-content assertions on deploy/deploy-server.sh for
#                      the US-352 / B-104 Step 1c one-shot backfill of drives
#                      11-20 via the new server compute path.  Verifies the
#                      script includes a backfill step that invokes
#                      `python -m src.server.cli.recompute_drive_analytics
#                      --drive-id-range 11-20`, is gated by an idempotent
#                      marker file so re-deploys skip cleanly, runs on the
#                      default flow (skipping --restart), and is best-effort
#                      (a failure logs a WARN but does not abort the deploy --
#                      the nightly server-analytics-batch.timer catches stale
#                      rows on its next tick).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-352) | Initial -- Sprint 41 / V0.27.17.  Pins the
#               |              | drives-11-20 backfill step shape so a future
#               |              | refactor cannot silently drop the marker, the
#               |              | range, or the best-effort discipline.
# 2026-05-21    | Rex (US-357) | V0.27.18 hotfix (I-042) -- added the
#               |              | outcome-not-observed gate tests: the marker
#               |              | write must be conditional on parsing the
#               |              | CLI's "success=N | skipped=N | failed=N"
#               |              | summary line AND requiring failed==0 +
#               |              | success>=1.  Closes the I-042 false-pass
#               |              | wrapper class at the deploy-script layer.
# ================================================================================
################################################################################

"""Static text assertions for the deploy-server.sh drives-11-20 backfill step."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-server.sh"


def _scriptText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


# ---- Existence + identity ---------------------------------------------------


def test_backfillStep_hasOperatorBanner():
    """A '--- Step N: ... backfill ... ---' banner must mark the step.

    Operators reading the deploy log need to see the backfill ran.  The
    banner also serves as a quick grep token when correlating a deploy
    with a marker-file presence on chi-srv-01.
    """
    text = _scriptText()
    banners = [
        line for line in text.splitlines()
        if line.strip().startswith('echo "--- Step')
        and "backfill" in line.lower()
        and "11-20" in line.lower()
    ]
    assert banners, (
        "deploy-server.sh must emit a '--- Step N: ... drives 11-20 "
        "backfill ... ---' banner so operators see the step ran"
    )


def test_backfillStep_referencesUs352AndB104():
    """Provenance lives in the banner / surrounding comment so future
    archaeology can trace the step back to its acceptance criteria.
    """
    text = _scriptText()
    assert "US-352" in text, "deploy-server.sh must cite US-352 on the backfill step"
    assert "B-104" in text, "deploy-server.sh must cite B-104 on the backfill step"


# ---- CLI invocation ---------------------------------------------------------


def test_backfillStep_invokesRecomputeCliWithDriveIdRange():
    """The backfill must call the on-demand recompute CLI with the exact
    11-20 range.  A typo here means the wrong drives get processed (or
    none -- if e.g. 12-20 lands, Drive 11 stays NULL contra the Spool
    FLAG-2 + Argus DB-state check ratification 2026-05-21).
    """
    text = _scriptText()
    assert "recompute_drive_analytics" in text, (
        "deploy-server.sh must invoke recompute_drive_analytics CLI"
    )
    assert "--drive-id-range 11-20" in text, (
        "deploy-server.sh must invoke recompute_drive_analytics with "
        "--drive-id-range 11-20 (US-352 acceptance criterion 1; Spool FLAG-2 "
        "+ Argus DB-check widened 12-20 -> 11-20 to include the Drive 11 "
        "knock-retard reference baseline)"
    )


def test_backfillStep_runsCliOnServerNotLocally():
    """The CLI needs chi-srv-01's .env (DATABASE_URL) + the server venv with
    sqlalchemy/pymysql -- run it ON the server via ssh, not from the
    operator's Windows / git-bash shell.  This mirrors the Step 4 DB
    table creation idiom: `ssh $HOST "... $REMOTE_VENV/bin/python ..."`.
    """
    text = _scriptText()
    lines = text.splitlines()
    cliLineIdx = [
        i for i, line in enumerate(lines)
        if "recompute_drive_analytics" in line and "--drive-id-range" in line
    ]
    assert cliLineIdx, "no recompute_drive_analytics --drive-id-range call found"
    callLine = lines[cliLineIdx[0]]
    # The line that invokes the CLI must thread through ssh + the server venv.
    assert "ssh" in callLine, (
        "backfill CLI invocation must SSH to the server (DATABASE_URL + venv "
        "live there); a local invocation would fail without chi-srv-01 DB access"
    )
    assert "REMOTE_VENV" in callLine or "obd2-server-venv" in callLine, (
        "backfill CLI invocation must use the server venv "
        "(sqlalchemy + pymysql are installed there)"
    )


# ---- Idempotency: marker-file guard -----------------------------------------


def test_backfillStep_usesGuardMarkerFile():
    """Acceptance criterion 6: 'BACKFILL_COMPLETE_V0_27_17=true written to a
    marker file after first successful run; subsequent deploys check marker
    and skip'.  The marker name must reference V0.27.17 + the 11-20 scope
    so a future backfill (different drives, different version) gets its
    own marker without collision.
    """
    text = _scriptText()
    assert ".backfill-V0.27.17" in text or ".backfill-v0.27.17" in text.lower(), (
        "deploy-server.sh must reference a version-tagged marker file "
        "(e.g. .backfill-V0.27.17-drives-11-20-complete) to gate re-runs"
    )
    assert "drives-11-20" in text or "drives_11_20" in text, (
        "marker filename must reference the drives-11-20 scope so future "
        "backfills don't collide on this marker"
    )


def test_backfillStep_checksMarkerBeforeRunning():
    """The script must `test -f` the marker before invoking the CLI; if
    the marker is present the step is a no-op (skip + echo 'idempotent').
    """
    text = _scriptText()
    # Locate the backfill banner, then scan forward for the guard pattern.
    bannerIdx = text.find("drives 11-20")
    assert bannerIdx > -1
    block = text[bannerIdx:bannerIdx + 3000]
    assert "test -f" in block, (
        "backfill step must use `test -f` to check the marker file before "
        "running the CLI (idempotent guard per acceptance criterion 6)"
    )


def test_backfillStep_writesMarkerOnSuccess():
    """After a successful CLI invocation, the marker file must be written
    so subsequent deploys skip.  Acceptance criterion 6 phrasing:
    'BACKFILL_COMPLETE_V0_27_17=true written to a marker file'.
    """
    text = _scriptText()
    assert "BACKFILL_COMPLETE_V0_27_17" in text, (
        "deploy-server.sh must write BACKFILL_COMPLETE_V0_27_17 marker "
        "contents on successful backfill (acceptance criterion 6 verbatim)"
    )


# ---- Flow gates -------------------------------------------------------------


def test_backfillStep_skippedUnderRestartOnly():
    """--restart is an operator escape hatch that shouldn't re-run schema
    or data migrations -- the backfill is gated behind `RESTART_ONLY = false`
    like Steps 1 / 3 / 4.5 / 4.6.
    """
    text = _scriptText()
    lines = text.splitlines()
    # Find the backfill banner line, then walk backwards to the nearest `if`
    # to confirm it's inside an `if [ "$RESTART_ONLY" = false ]` block.
    bannerLineIdx = [
        i for i, line in enumerate(lines)
        if line.strip().startswith('echo "--- Step')
        and "11-20" in line.lower()
        and "backfill" in line.lower()
    ]
    assert bannerLineIdx, "could not locate the backfill banner line"
    bannerIdx = bannerLineIdx[0]
    enclosingIf = None
    depth = 0
    for j in range(bannerIdx - 1, -1, -1):
        stripped = lines[j].strip()
        if stripped.startswith("fi"):
            depth += 1
        elif stripped.startswith("if "):
            if depth > 0:
                depth -= 1
                continue
            enclosingIf = stripped
            break
    assert enclosingIf is not None, (
        "backfill step is not enclosed by an `if` -- expected gating on "
        "$RESTART_ONLY = false to skip the step on --restart"
    )
    assert "RESTART_ONLY" in enclosingIf and "false" in enclosingIf, (
        f"backfill step is enclosed by {enclosingIf!r}; expected "
        f"`if [ \"$RESTART_ONLY\" = false ]` so --restart skips the backfill"
    )


def test_backfillStep_runsInDefaultFlowNotJustInit():
    """The backfill runs on the default flow (every deploy until the
    marker is set), not only on --init.  A common deploy regression is
    nesting a new step inside the --init block; this test catches that.
    """
    text = _scriptText()
    lines = text.splitlines()
    callLineIdx = [
        i for i, line in enumerate(lines)
        if "recompute_drive_analytics" in line and "--drive-id-range" in line
    ]
    assert callLineIdx, "no --drive-id-range call found"
    for idx in callLineIdx:
        nested_init_only = False
        depth = 0
        for j in range(idx - 1, -1, -1):
            stripped = lines[j].strip()
            if stripped.startswith("fi"):
                depth += 1
            elif stripped.startswith("if "):
                if depth > 0:
                    depth -= 1
                    continue
                if "INIT" in stripped and "true" in stripped:
                    nested_init_only = True
                break
        assert not nested_init_only, (
            f"backfill call on line {idx + 1} is nested inside an INIT-only "
            f"block; per US-352 acceptance #6 it must run on the default flow"
        )


# ---- Ordering ---------------------------------------------------------------


def test_backfillStep_runsAfterMigrationsAndAnalyticsBatchInstall():
    """The compute path the CLI invokes depends on:
        - Step 4.5 schema migrations (so drive_statistics composite-PK shape
          + drive_summary analytics columns are present)
        - Step 4.8 analytics-batch unit install (so a backfill failure is
          backstopped by the nightly timer)

    Both must precede the backfill in deploy-server.sh.
    """
    text = _scriptText()
    migrationIdx = text.find("--run-all")
    batchInstallIdx = text.find("server-analytics-batch.service")
    backfillIdx = text.find("recompute_drive_analytics")
    assert migrationIdx > -1, "could not locate --run-all migration anchor"
    assert batchInstallIdx > -1, "could not locate server-analytics-batch.service anchor"
    assert backfillIdx > -1, "could not locate recompute_drive_analytics call"
    assert migrationIdx < backfillIdx, (
        "Step 4.5 migrations must precede the backfill (schema must be in "
        "place before the compute path UPDATEs analytics columns)"
    )
    assert batchInstallIdx < backfillIdx, (
        "Step 4.8 analytics-batch install must precede the backfill so the "
        "nightly timer is in place to catch any backfill failures"
    )


def test_backfillStep_runsBeforeServiceRestart():
    """Step ordering invariant: the backfill must run BEFORE the obd-server
    restart so the running daemon doesn't see partial analytics rows mid-
    UPDATE.  Mirrors test_migrationStep_runsBeforeServiceStart.

    We scan the executable body only (post the ``set -e`` marker) -- the
    file header documents Step 6 in plain text, which would otherwise skew
    ``text.find('systemctl restart obd-server')`` toward the comment block.
    """
    text = _scriptText()
    setEOffset = text.find("\nset -e")
    assert setEOffset > -1, "could not locate `set -e` anchor"
    body = text[setEOffset:]
    backfillIdx = body.find("recompute_drive_analytics")
    restartIdx = body.find("systemctl restart obd-server")
    assert backfillIdx > -1, "recompute_drive_analytics call not found in body"
    assert restartIdx > -1, "systemctl restart obd-server line not found in body"
    assert backfillIdx < restartIdx, (
        "backfill must run before the obd-server restart so live requests "
        "after the restart see the fully-backfilled analytics rows"
    )


# ---- Best-effort fault tolerance --------------------------------------------


def test_backfillStep_isBestEffort_doesNotExitOnFailure():
    """Per the established Step 4.6 stranded-row backfill idiom: a backfill
    failure logs a WARN but does NOT abort the deploy.  The nightly
    server-analytics-batch.timer will retry from --all-stale.

    We enforce this by asserting the backfill block contains a WARN line
    matching the failure path AND does NOT contain `exit 1` between the
    backfill banner and the next `fi` (which would `exit` on failure).
    """
    text = _scriptText()
    bannerIdx = text.find("drives 11-20")
    assert bannerIdx > -1
    # Block scope: from the banner forward to the next 'echo ""' / 'Step' marker.
    nextStepIdx = text.find('echo "--- Step', bannerIdx + 1)
    if nextStepIdx == -1:
        nextStepIdx = len(text)
    block = text[bannerIdx:nextStepIdx]
    assert "WARN" in block.upper(), (
        "backfill step must include a WARN log on failure (best-effort "
        "idiom from Step 4.6 stranded-row backfill)"
    )
    assert "exit 1" not in block, (
        "backfill step must NOT `exit 1` on failure -- a deploy with a "
        "stale-but-otherwise-healthy backfill is better than an aborted "
        "deploy; the nightly server-analytics-batch.timer retries"
    )


# ---- Marker contents pin ----------------------------------------------------


def test_backfillStep_markerFileNameStableAndDocumented():
    """Pin the marker filename so a future refactor that changes the name
    (and silently re-runs the backfill on the next deploy, eating row
    rewrites + a brief deploy stall) trips RED here first.
    """
    text = _scriptText()
    # The marker name should appear in at least two places: the test-f
    # guard and the write-on-success block.  Both should reference the
    # same identifier; we enforce uniqueness via the assertion that we
    # find at least 2 occurrences of the file path stem.
    occurrences = text.count(".backfill-V0.27.17")
    assert occurrences >= 2, (
        f"marker filename should appear at least twice (guard check + "
        f"write-on-success); found {occurrences} occurrences"
    )


# ---- I-042 outcome-not-observed gate (V0.27.18 hotfix US-357) ---------------


def _backfillBlock() -> str:
    """Return the text of the Step 4.9 backfill block (banner to next step).

    Many of the I-042 assertions scope to this block to avoid false matches
    on the file header / other steps.
    """
    text = _scriptText()
    bannerIdx = text.find("Step 4.9: Backfilling drives 11-20")
    if bannerIdx == -1:
        bannerIdx = text.find("drives 11-20")
    assert bannerIdx > -1, "could not locate backfill step banner"
    nextStepIdx = text.find('echo "--- Step', bannerIdx + 1)
    if nextStepIdx == -1:
        nextStepIdx = len(text)
    return text[bannerIdx:nextStepIdx]


def test_backfillStep_referencesI042AndUs357InCommentary():
    """The block's commentary must cite I-042 and US-357 so future
    archaeology can trace the marker-gate fix back to its source.
    """
    text = _scriptText()
    assert "I-042" in text, (
        "deploy-server.sh must cite I-042 on the backfill step "
        "(US-357 V0.27.18 hotfix provenance)"
    )
    assert "US-357" in text, (
        "deploy-server.sh must cite US-357 on the backfill step "
        "(V0.27.18 hotfix provenance)"
    )


def test_backfillStep_capturesCliOutputForOutcomeParse():
    """The CLI invocation must capture stdout+stderr so the wrapper can
    parse the success/failed summary line.  A blind fire-and-forget
    invocation (the pre-I-042 V0.27.17 shape) cannot observe outcome.
    """
    block = _backfillBlock()
    # Either capture into a variable or pipe to a parser -- both are
    # acceptable, but we MUST see one of these idioms.
    has_capture = (
        "$(ssh" in block and "recompute_drive_analytics" in block
    ) or (
        "BACKFILL_OUTPUT=" in block
    ) or (
        "tee " in block and "recompute_drive_analytics" in block
    )
    assert has_capture, (
        "Step 4.9 must capture the recompute_drive_analytics CLI output "
        "(via $() / BACKFILL_OUTPUT= / tee) so the marker-write gate can "
        "parse the 'success=N | failed=N' summary line (I-042 fix)"
    )


def test_backfillStep_parsesSuccessAndFailedFromCliSummary():
    """The wrapper must extract numeric counts from the CLI's summary line
    in the EXACT format the CLI emits at
    ``src/server/cli/recompute_drive_analytics.py:253``:

        "recompute_drive_analytics | done | success=%d | skipped=%d | failed=%d"

    A test pin on the parse pattern catches CLI-format drift early.
    """
    block = _backfillBlock()
    # The wrapper must reference success= AND failed= in the parse logic
    # (sed/grep/awk -- all acceptable).
    assert "success=" in block, (
        "Step 4.9 must parse 'success=N' from the CLI summary line "
        "(I-042 marker gate)"
    )
    assert "failed=" in block, (
        "Step 4.9 must parse 'failed=N' from the CLI summary line "
        "(I-042 marker gate)"
    )


def test_backfillStep_markerWriteIsGatedOnFailedZero():
    """I-042: the marker write line (``printf 'BACKFILL_COMPLETE_V0_27_17''``)
    must be enclosed inside a conditional that requires the parsed
    failed-count to be zero.  Without this gate the V0.27.17 false-pass
    recurs: CLI exits 0 with 10/10 failures and the marker still writes.
    """
    block = _backfillBlock()
    lines = block.splitlines()
    markerWriteLineIdx = [
        i for i, line in enumerate(lines)
        if "BACKFILL_COMPLETE_V0_27_17" in line and "printf" in line
    ]
    assert markerWriteLineIdx, (
        "could not locate the marker-write line "
        "(printf 'BACKFILL_COMPLETE_V0_27_17...' > marker)"
    )
    # Walk backwards from the marker-write line to find the nearest
    # enclosing 'if'.  That conditional MUST reference failed-count.
    enclosingIf = None
    depth = 0
    for j in range(markerWriteLineIdx[0] - 1, -1, -1):
        stripped = lines[j].strip()
        if stripped.startswith("fi"):
            depth += 1
        elif stripped.startswith("if "):
            if depth > 0:
                depth -= 1
                continue
            enclosingIf = stripped
            break
    assert enclosingIf is not None, (
        "marker write must be inside an 'if' (I-042 fix: gate on "
        "failed-count==0); found no enclosing if"
    )
    # The conditional must reference BACKFILL_FAILED (or equivalent
    # failed-count variable) AND require it to be zero.
    assert (
        ("BACKFILL_FAILED" in enclosingIf or "failed" in enclosingIf.lower())
        and ("-eq 0" in enclosingIf or "= 0" in enclosingIf)
    ), (
        f"marker-write 'if' must require failed-count==0 to write the "
        f"marker (I-042 fix); enclosing if is: {enclosingIf!r}"
    )


def test_backfillStep_markerWriteAlsoRequiresAtLeastOneSuccess():
    """I-042 belt-and-suspenders: the marker gate should also require
    success>=1.  Without this, a degenerate input (no drives in range;
    CLI logs success=0 failed=0) would still trigger a marker write
    and silently mark the backfill "done" with zero actual work.
    """
    block = _backfillBlock()
    lines = block.splitlines()
    markerWriteLineIdx = [
        i for i, line in enumerate(lines)
        if "BACKFILL_COMPLETE_V0_27_17" in line and "printf" in line
    ]
    assert markerWriteLineIdx
    enclosingIf = None
    depth = 0
    for j in range(markerWriteLineIdx[0] - 1, -1, -1):
        stripped = lines[j].strip()
        if stripped.startswith("fi"):
            depth += 1
        elif stripped.startswith("if "):
            if depth > 0:
                depth -= 1
                continue
            enclosingIf = stripped
            break
    assert enclosingIf is not None
    assert (
        ("BACKFILL_SUCCESS" in enclosingIf or "success" in enclosingIf.lower())
        and ("-ge 1" in enclosingIf or "-gt 0" in enclosingIf
             or ">= 1" in enclosingIf)
    ), (
        f"marker-write 'if' must also require success>=1 to rule out the "
        f"degenerate zero-input path (I-042 fix); enclosing if is: "
        f"{enclosingIf!r}"
    )


def test_backfillStep_logsParsedCountsOnFailure():
    """When the wrapper takes the failure branch, the WARN must include
    the parsed failed/success counts so the operator can see WHY the
    marker was not written (vs. the pre-I-042 silent success).
    """
    block = _backfillBlock()
    lines = block.splitlines()
    # Locate the 'else' branch of the marker gate.
    elseIdx = [
        i for i, line in enumerate(lines)
        if line.strip() == "else" or line.strip().startswith("else ")
    ]
    assert elseIdx, (
        "Step 4.9 must have an 'else' branch on the marker gate that "
        "WARNs without writing the marker"
    )
    # The next few lines after each 'else' should include the WARN line.
    foundWarnWithCounts = False
    for idx in elseIdx:
        for j in range(idx, min(idx + 5, len(lines))):
            line = lines[j]
            if "WARN" in line and (
                "failed" in line.lower() or "success" in line.lower()
                or "${BACKFILL" in line
            ):
                foundWarnWithCounts = True
                break
        if foundWarnWithCounts:
            break
    assert foundWarnWithCounts, (
        "I-042 fix: the failure-branch WARN should report the parsed "
        "failed/success counts (or BACKFILL_* variables) so operators "
        "can see why the marker was withheld"
    )


def test_backfillStep_markerAbsentOnTotalFailureNotWritten():
    """The most important I-042 regression test: a 10/10 failure (the
    exact V0.27.17 production state) MUST NOT result in a marker write.

    We assert this structurally: there is NO unconditional ``printf
    'BACKFILL_COMPLETE_V0_27_17`` write outside the failed==0 gate.
    Searches the entire block; every marker-write reference must be
    inside an ``if`` that gates on the parsed failed-count.
    """
    block = _backfillBlock()
    lines = block.splitlines()
    markerWrites = [
        (i, line) for i, line in enumerate(lines)
        if "printf" in line and "BACKFILL_COMPLETE_V0_27_17" in line
    ]
    assert markerWrites, "no marker-write line found"
    for idx, _line in markerWrites:
        enclosingIf = None
        depth = 0
        for j in range(idx - 1, -1, -1):
            stripped = lines[j].strip()
            if stripped.startswith("fi"):
                depth += 1
            elif stripped.startswith("if "):
                if depth > 0:
                    depth -= 1
                    continue
                enclosingIf = stripped
                break
        assert enclosingIf is not None and (
            "failed" in enclosingIf.lower() or "FAILED" in enclosingIf
        ), (
            f"marker-write at block line {idx} is NOT inside a "
            f"failed-count gate; enclosing if = {enclosingIf!r}.  This "
            f"would re-introduce I-042 (marker written despite 10/10 "
            f"backfill failures)."
        )
