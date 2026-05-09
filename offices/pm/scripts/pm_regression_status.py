#!/usr/bin/env python3
"""
pm_regression_status.py -- Query the regression manifest.

Reports which user-facing features are OK / STALE / NEVER-validated against
the real-hardware drill cadence Mike defined 2026-05-08:
"main = fully validated stable; sprint branches stay deployed-but-pre-merge
until real-hardware drill validates affected features."

Usage:
  python offices/pm/scripts/pm_regression_status.py             # full status report
  python offices/pm/scripts/pm_regression_status.py --json      # machine-readable
  python offices/pm/scripts/pm_regression_status.py --stale     # only show stale + never
  python offices/pm/scripts/pm_regression_status.py --by-sprint 27  # which features sprint 27 touched
  python offices/pm/scripts/pm_regression_status.py --next      # next validation triggers (Drive N? Drain N?)

Exit codes:
  0  manifest valid + report generated
  1  manifest has stale or never-validated features (use in CI gate)
  2  manifest file missing or invalid

Stdlib-only Python (matches offices/pm/scripts/ convention).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "offices" / "pm" / "regression_manifest.json"


def loadManifest(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} invalid JSON: {exc}", file=sys.stderr)
        sys.exit(2)


def featureStaleness(feature: dict, today: date) -> tuple[str, int | None]:
    """Return (status_label, days_stale_or_None).

    status_label: 'OK' | 'STALE' | 'NEVER'
    """
    lastValidated = feature.get("lastValidated")
    if not lastValidated:
        return "NEVER", None
    try:
        validatedDate = datetime.strptime(lastValidated, "%Y-%m-%d").date()
    except ValueError:
        return "NEVER", None
    daysAgo = (today - validatedDate).days
    threshold = feature.get("staleThresholdDays", 30)
    if daysAgo > threshold:
        return "STALE", daysAgo
    return "OK", daysAgo


def renderReport(manifest: dict, staleOnly: bool = False) -> tuple[str, dict]:
    """Build human-readable report + summary counts."""
    today = date.today()
    features = manifest.get("features", [])
    lines: list[str] = []
    lines.append(f"Regression Status (as of {today.isoformat()})")
    lines.append("=" * 60)
    lines.append("")

    counts = {"OK": 0, "STALE": 0, "NEVER": 0}
    byStatus = {"OK": [], "STALE": [], "NEVER": []}

    for feat in features:
        status, daysAgo = featureStaleness(feat, today)
        counts[status] += 1
        byStatus[status].append((feat, daysAgo))

    if not staleOnly and byStatus["OK"]:
        lines.append("OK (within threshold):")
        for feat, daysAgo in byStatus["OK"]:
            lines.append(f"  {feat['id']:<6} {feat['name']:<60} last {feat['lastValidated']} ({feat['validatedBy']})")
        lines.append("")

    if byStatus["STALE"]:
        lines.append("STALE (overdue real-hardware verify):")
        for feat, daysAgo in byStatus["STALE"]:
            lines.append(
                f"  {feat['id']:<6} {feat['name']:<60} last {feat['lastValidated']} ({daysAgo}d ago; "
                f"threshold {feat['staleThresholdDays']}d)"
            )
        lines.append("")

    if byStatus["NEVER"]:
        lines.append(">>> NEVER VALIDATED IN REAL LIFE:")
        for feat, _ in byStatus["NEVER"]:
            lines.append(f"  {feat['id']:<6} {feat['name']:<60} {feat['validatedBy']}")
        lines.append("")

    lines.append(f"Summary: {counts['OK']} OK, {counts['STALE']} STALE, {counts['NEVER']} NEVER")
    return "\n".join(lines), counts


def renderNextTriggers(manifest: dict) -> str:
    """Suggest which real-hardware drills would re-validate which features."""
    today = date.today()
    features = manifest.get("features", [])
    byMethod: dict[str, list[dict]] = {}
    for feat in features:
        status, _ = featureStaleness(feat, today)
        if status == "OK":
            continue
        method = feat.get("validationMethod", "manual_attestation")
        byMethod.setdefault(method, []).append(feat)

    lines = ["NEXT VALIDATION TRIGGERS:", ""]
    triggerNames = {
        "real_engine_on_test": "Drive N IRL (engine on, BT pair, drive, return home)",
        "real_drain_test": "Drain Test N (full discharge cycle on UPS)",
        "manual_attestation": "Manual attestation drill (Mike runs + confirms)",
        "automatic": "Re-deploy (auto-validates lifecycle features)",
    }
    for method in ["real_engine_on_test", "real_drain_test", "manual_attestation", "automatic"]:
        feats = byMethod.get(method, [])
        if not feats:
            continue
        lines.append(f"  {triggerNames.get(method, method)}:")
        ids = [f["id"] for f in feats]
        lines.append(f"    would re-validate {', '.join(ids)} ({len(feats)} feature(s))")
        lines.append("")
    return "\n".join(lines)


def filterBySprint(manifest: dict, sprintNumber: int) -> str:
    """List features the given sprint touched (per affectedBySprints)."""
    features = manifest.get("features", [])
    affected = [f for f in features if sprintNumber in (f.get("affectedBySprints") or [])]
    if not affected:
        return f"No features tagged as affected by Sprint {sprintNumber}."
    lines = [f"Features affected by Sprint {sprintNumber}:", ""]
    today = date.today()
    for feat in affected:
        status, daysAgo = featureStaleness(feat, today)
        suffix = f"{daysAgo}d ago" if daysAgo is not None else "never IRL"
        lines.append(f"  [{status:<5}] {feat['id']:<6} {feat['name']:<55} ({suffix})")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--path", default=str(DEFAULT_MANIFEST_PATH), help="Manifest path override")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--stale", action="store_true", help="Only show STALE + NEVER")
    parser.add_argument("--by-sprint", type=int, help="Show features affected by sprint N")
    parser.add_argument("--next", action="store_true", help="Show next validation triggers")
    args = parser.parse_args(argv)

    manifest = loadManifest(Path(args.path))

    if args.by_sprint is not None:
        print(filterBySprint(manifest, args.by_sprint))
        return 0

    if args.json:
        report, counts = renderReport(manifest, staleOnly=args.stale)
        out = {
            "manifest_version": manifest.get("manifestVersion"),
            "as_of": date.today().isoformat(),
            "counts": counts,
            "report": report,
        }
        print(json.dumps(out, indent=2))
    else:
        report, counts = renderReport(manifest, staleOnly=args.stale)
        print(report)
        if args.next or counts["STALE"] > 0 or counts["NEVER"] > 0:
            print()
            print(renderNextTriggers(manifest))

    if counts["STALE"] > 0 or counts["NEVER"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
