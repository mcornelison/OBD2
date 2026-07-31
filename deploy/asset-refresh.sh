#!/usr/bin/env bash
################################################################################
# asset-refresh.sh — US-495 (S2, F-111) /opt stale-asset force-refresh guard.
#
# WHY THIS EXISTS
#   The two Pi asset steps (step_install_splash_assets / step_install_dashboard_
#   assets) only ever installed ON TOP of /opt. Nothing was ever REMOVED, so a
#   file from a retired kit generation lives in /opt forever. That is how the Pi
#   came to render a top-bar wordmark ("Eclipse ODB2") that exists nowhere in
#   this repo, through deploy after deploy that each reported success.
#
#   It is worse than a cosmetic leftover, because eclipse-states-http searches
#   `--assets-dir /opt/splash` BEFORE `/opt/dashboard`. One forgotten
#   dashboard.html in /opt/splash SHADOWS the real one in /opt/dashboard
#   permanently -- and the dashboard step, which only ever writes to
#   /opt/dashboard, can never dislodge it.
#
# WHAT IT DOES
#   Makes an installed dir an EXACT mirror of what the repo vouches for:
#     1. install every manifest asset that the source kit ships;
#     2. PRUNE everything else -- including a manifest asset the source kit no
#        longer ships (a stale copy the repo cannot vouch for must not be
#        served; an honest 404 beats a confident stale render);
#     3. VERIFY each installed file byte-for-byte against its source and FAIL
#        LOUD if a write did not take.
#
#   /opt/<kit> is DEPLOY-OWNED, not hand-edited: anything dropped there
#   out-of-band is pruned by design. Files a DIFFERENT installer legitimately
#   owns (the splash kit's own install.sh writes the SVGs + the shutdown
#   surface; the deploy writes version.txt) are passed as the keep-list so one
#   installer never deletes another's work mid-deploy.
#
# POSTURE vs A-9 (deliberate, and a change worth reading)
#   ABSENCE still warns and continues -- a Pi deploy without the UI kit ships
#   the rest of the tier. A FAILED WRITE now BLOCKS. Those are different facts:
#   absence is a Pi that was never given a UI; a failed write is a deploy that
#   believes it shipped one and did not. Continuing past the second is what
#   produces "deploy OK" over a stale surface, and sends the operator to debug
#   the UI instead of the deploy (the A-16 lesson).
#
# Usage:
#   ASSET_SUDO=  . deploy/asset-refresh.sh          # unprivileged (tests)
#   . deploy/asset-refresh.sh                        # sudo (on the Pi)
#   refresh_asset_dir <srcDir> <dstDir> "<manifest>" ["<keepList>"]
#
# Author:  Ralph Agent (Rex)
# Created: 2026-07-29 -- Sprint 66 US-495 (/opt force-refresh)
################################################################################

# refresh_asset_dir SRC DST MANIFEST [KEEP]
#
#   SRC      source kit dir (on the Pi: ${PI_PATH}/specs/UI/dist/<kit>)
#   DST      installed dir  (/opt/splash | /opt/dashboard)
#   MANIFEST space-separated basenames this step installs + owns
#   KEEP     space-separated basenames another installer owns -- never pruned,
#            never installed, never verified here
#
# Returns 0 on success or on an absent source kit (A-9); non-zero if an
# installed file does not match its source.
refresh_asset_dir() {
    local srcDir="$1" dstDir="$2" manifest="$3" keep="${4:-}"
    # `${ASSET_SUDO-sudo}` (no colon): UNSET -> sudo, set-but-EMPTY -> nothing.
    # A colon form would collapse the deliberate empty back to sudo and the
    # unprivileged test path would silently escalate.
    local sudoCmd="${ASSET_SUDO-sudo}"

    if [ ! -d "$srcDir" ]; then
        echo "WARN: asset kit not present at $srcDir -- skipping refresh; deploy continues (A-9)." >&2
        return 0
    fi

    $sudoCmd install -d -m 0755 "$dstDir"

    # 1. Install what the source kit vouches for. `installed` is the authority
    #    for both the prune and the verify below -- a manifest entry the kit did
    #    not ship never enters it, so it is pruned rather than left serving.
    local installed="" asset
    for asset in $manifest; do
        if [ -f "$srcDir/$asset" ]; then
            $sudoCmd install -m 0644 "$srcDir/$asset" "$dstDir/$asset"
            installed="$installed $asset"
            echo "installed $asset -> $dstDir/"
        else
            echo "WARN: asset $asset missing in $srcDir -- not installed (A-9)." >&2
        fi
    done

    # 2. Prune. Anything in DST that this run did not install and no other
    #    installer claims is a retired generation: remove it, and SAY SO.
    local existing base
    for existing in "$dstDir"/*; do
        [ -f "$existing" ] || continue
        base="$(basename "$existing")"
        case " $installed $keep " in
            *" $base "*) continue ;;
        esac
        $sudoCmd rm -f "$existing"
        echo "pruned stale asset $base from $dstDir (not vouched for by $srcDir)"
    done

    # 3. Verify. `install` can report success and still leave the destination
    #    untouched (read-only mount, full disk, a shadowing mount point), which
    #    is precisely the silent failure this whole guard exists to surface.
    local mismatched=""
    for asset in $installed; do
        if ! cmp -s "$srcDir/$asset" "$dstDir/$asset"; then
            mismatched="$mismatched $asset"
        fi
    done
    if [ -n "$mismatched" ]; then
        echo "ERROR: $dstDir does not match $srcDir after install --$mismatched" >&2
        echo "ERROR: the Pi would keep serving stale assets; fix the write path and re-deploy." >&2
        return 1
    fi

    echo "verified $dstDir matches $srcDir ($(echo $installed | wc -w) asset(s))"
    return 0
}
