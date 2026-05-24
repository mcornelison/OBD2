#!/usr/bin/env python3
"""
chain_validate_manifest_bump.py -- /chain-validated Phase 3 support.

For each feature ID supplied (typically the aggregated validatesFeatures
union from chain_validate_aggregate.py), bump lastValidated to the chain
merge date and stamp validatedBy with the chain-merge label.

Per CIO 2026-05-10 chain-end-merge rule: when the whole V0.X chain
validates IRL + merges to main, every feature any sprint in the chain
validated re-marks its lastValidated date on the manifest.  This is the
manifest-side companion to /sprint-validated's per-sprint phase 3 bump.

Usage:
  # Mutate in-place against the default manifest:
  python offices/pm/scripts/chain_validate_manifest_bump.py \\
      --features F-005 F-007 \\
      --label "by chain merge V0.27.5" \\
      --date 2026-05-15

  # Preview (no write):
  python offices/pm/scripts/chain_validate_manifest_bump.py \\
      --features F-005 F-007 --label "..." --date 2026-05-15 --dry-run

  # Manifest path override (test harness):
  python offices/pm/scripts/chain_validate_manifest_bump.py \\
      --path /tmp/manifest.json --features F-001 --label "..." --date 2026-06-01

Exit codes:
  0  success (bumped + report printed)
  1  unknown feature IDs (none of the supplied IDs matched the manifest)
  2  file/parse error

Stdlib-only (matches offices/pm/scripts/ convention).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "offices" / "pm" / "regression_manifest.json"


def bumpManifestForChain(
    manifestPath: Path,
    featureIds: list[str],
    validationLabel: str,
    mergeDate: str,
    dryRun: bool = False,
) -> list[str]:
    """Bump lastValidated + validatedBy for matching features.

    Args:
        manifestPath: Path to regression_manifest.json.
        featureIds: Feature IDs to bump (e.g. ['F-005', 'F-007']).
            Unknown IDs are skipped (not in the returned list).
        validationLabel: New validatedBy string (e.g. 'by chain merge V0.27.5').
        mergeDate: ISO date string (YYYY-MM-DD) to write as lastValidated.
        dryRun: If True, do not write the file; still returns the bumped list.

    Returns:
        Sorted list of feature IDs that were actually bumped.
    """
    if not manifestPath.exists():
        print(f"ERROR: {manifestPath} not found", file=sys.stderr)
        sys.exit(2)

    try:
        manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {manifestPath} invalid JSON: {exc}", file=sys.stderr)
        sys.exit(2)

    wanted = set(featureIds)
    bumped: list[str] = []
    for feat in manifest.get("features", []):
        if feat.get("id") in wanted:
            feat["lastValidated"] = mergeDate
            feat["validatedBy"] = validationLabel
            bumped.append(feat["id"])

    manifest["lastUpdated"] = mergeDate
    manifest["lastUpdatedBy"] = f"chain_validate_manifest_bump.py ({validationLabel})"

    if not dryRun:
        manifestPath.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    return sorted(bumped)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--path",
        default=str(DEFAULT_MANIFEST_PATH),
        help="regression_manifest.json path override",
    )
    parser.add_argument(
        "--features",
        nargs="+",
        required=True,
        help="Feature IDs to bump (e.g. F-005 F-007)",
    )
    parser.add_argument(
        "--label",
        required=True,
        help='New validatedBy label (e.g. "by chain merge V0.27.5")',
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="ISO date for lastValidated (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing",
    )
    args = parser.parse_args(argv)

    bumped = bumpManifestForChain(
        Path(args.path),
        featureIds=args.features,
        validationLabel=args.label,
        mergeDate=args.date,
        dryRun=args.dry_run,
    )

    unknown = sorted(set(args.features) - set(bumped))
    print(f"Manifest: {args.path}")
    print(f"Chain label: {args.label}")
    print(f"Merge date: {args.date}")
    print(f"Bumped {len(bumped)} feature(s): {', '.join(bumped) if bumped else '(none)'}")
    if unknown:
        print(f"WARN: unknown feature ID(s) skipped: {', '.join(unknown)}", file=sys.stderr)
    if args.dry_run:
        print("(dry-run: manifest not written)")

    if not bumped:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
