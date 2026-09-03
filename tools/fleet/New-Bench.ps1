<#
.SYNOPSIS
  Leases one worktree ("bench") to one agent for one ticket, fully provisioned.

.DESCRIPTION
  Rewritten for OBD2v3 after the Step 0-5f migration. Everything here exists
  because a fresh worktree is a checkout of TRACKED files only -- every
  untracked-but-required file has to be stamped in, or the bench fails in a
  confusing way that looks like broken code.

.EXAMPLE
  .\New-Bench.ps1 -Role Dev -Ticket 1001 -Slug ingest-retry `
      -Surface "src/pi/obdii/**","tests/pi/obdii/**"
#>
[CmdletBinding()]
param(
  # Roster is validated at RUNTIME against fleet.json, never by a ValidateSet.
  # A hardcoded set carries the previous project's roster -- this one listed
  # tester/tuner/uideveloper and omitted 'drpixel', so that office could never
  # lease a bench and the error blamed the caller.
  [Parameter(Mandatory)][string]$Role,
  [Parameter(Mandatory)][string]$Ticket,
  [Parameter(Mandatory)][string]$Slug,
  [string[]]$Surface  = @('**'),
  [string]$ProjectRoot,
  [switch]$SkipVenv,
  [switch]$Launch
)

$ErrorActionPreference = 'Stop'

# Every office now uses claude.md (normalised 2026-08-25 -- previously a mix of
# claude.md / CLAUDE.md / projectManager.md / tester.md, which was invisible on
# case-insensitive Windows and would have broken on the share or any
# case-sensitive tool). The map stays rather than collapsing to a string: it is
# the one place that knows the roles, and it fails loudly for an unmapped one.
# Integrator works from trunk and has no office.


# ProjectRoot: walk up from this script for fleet.json -- depth-independent,
# and it cannot silently point at another project's root.
if (-not $ProjectRoot) {
  $probe = $PSScriptRoot
  while ($probe) {
    if (Test-Path (Join-Path $probe 'fleet.json')) { $ProjectRoot = $probe; break }
    $parent = Split-Path $probe -Parent
    if (-not $parent -or $parent -eq $probe) { break }
    $probe = $parent
  }
}
if (-not $ProjectRoot) { throw "fleet.json not found above $PSScriptRoot. Pass -ProjectRoot." }

$cfg = Get-Content (Join-Path $ProjectRoot 'fleet.json') -Raw | ConvertFrom-Json

. (Join-Path $PSScriptRoot 'FleetRoles.ps1')
$roleRecs   = Get-FleetRoles -Cfg $cfg -OfficesRoot (Join-Path $cfg.share 'offices')
$roleSlugs  = @($roleRecs | ForEach-Object { $_.slug })
if ($Role -notin (@($roleSlugs) + 'Integrator')) {
  throw "Unknown role '$Role'. This project has: $($roleSlugs -join ', ') (plus Integrator)."
}
$roleRec = $roleRecs | Where-Object { $_.slug -eq $Role } | Select-Object -First 1

# Role -> boot context file, GENERATED from the fleet.json roster. Each office's
# CHARTER.md is its mandate. Never hardcode this map: an unmapped role fails at
# lease time, and a role that is in the map but not in the project is worse --
# it leases a bench whose charter import points at a file that never existed.
$roleContext = @{}
foreach ($r in $roleSlugs) { $roleContext[$r] = "$r\CHARTER.md" }

$name   = ('{0}-{1}-{2}' -f $Role.ToLower(), $Ticket, $Slug)
$branch = ('{0}/{1}-{2}'  -f $Role.ToLower(), $Ticket, $Slug)
$wt     = Join-Path $cfg.worktrees $name
$stamp  = Join-Path $ProjectRoot '.stamp'

if (Test-Path $wt) { throw "Bench already leased: $wt" }

# --- 1. the worktree -------------------------------------------------------
# git refuses to check the same branch out twice. That refusal IS the mutual
# exclusion between agents -- it is not a convention anyone has to remember.
git --git-dir=$($cfg.bare) fetch origin
git --git-dir=$($cfg.bare) worktree add -b $branch $wt "origin/$($cfg.trunkBranch)"

# --- 1b. per-project Claude config ------------------------------------------
# Must exist BEFORE the agent launches. An isolated config dir inherits nothing:
# no credentials means "Not logged in" (fatal for a headless agent), and no
# settings.json means the git and config guards SILENTLY DO NOT RUN.
& (Join-Path $PSScriptRoot 'Initialize-ProjectConfig.ps1') -FleetJson (Join-Path $ProjectRoot 'fleet.json')

# --- 2. stamps -------------------------------------------------------------
# A worktree gets TRACKED files only. Anything gitignored-but-required has to be
# stamped in, or the bench fails in a way that looks like broken code.
#
# The manifest comes from fleet.json, NOT from a list in this script. fleet.json
# is the SSOT; a second hardcoded list is one fact with two homes, and the copy
# in here carried the previous project's files (.env, deploy.conf, .superpowers)
# which do not exist in every project.
foreach ($rel in @($cfg.stamp)) {
  $isDir = $rel.EndsWith('/') -or $rel.EndsWith('\')
  $clean = $rel.TrimEnd('/','\')
  $src   = Join-Path $stamp $clean
  $dst   = Join-Path $wt    $clean
  if (-not (Test-Path $src)) {
    throw "Stamp source missing: $src`nfleet.json declares '$rel' but .stamp\ does not have it. Stamp it in, or correct the manifest."
  }
  $parent = Split-Path $dst -Parent
  if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  if ($isDir -or (Get-Item $src).PSIsContainer) {
    Copy-Item $src $dst -Recurse -Force
  } else {
    Copy-Item $src $dst -Force
    $a = (Get-FleetFileHash $src)
    $b = (Get-FleetFileHash $dst)
    if ($a -ne $b) { throw "Stamp mismatch on $rel" }
  }
  Write-Host ("  stamped {0}" -f $rel) -ForegroundColor DarkGray
}

# --- 3. environment --------------------------------------------------------
# PYTHONUTF8: without it, 34 tests fail with UnicodeDecodeError on cp1252 and
#   look exactly like real breakage.
# FLEET_SHARE: tools/pm/_paths.py raises without it. That raise is deliberate --
#   the silent-fallback version read stale data in trunk and worked nowhere else.
@"
`$env:PYTHONUTF8 = '1'
`$env:FLEET_SHARE = '$($cfg.share)\offices'
`$env:CLAUDE_CONFIG_DIR = '$ProjectRoot\.claude-config'   # per-project config: the user-level dir is shared by EVERY agent in EVERY project
`$env:OBD2_REPO_ROOT = '$wt'
. '$wt\.venv\Scripts\Activate.ps1'
Set-Location '$wt'
Write-Host 'Bench $name  |  branch $branch' -ForegroundColor Green
Write-Host 'Surface: $($Surface -join ", ")' -ForegroundColor DarkGray
"@ | Set-Content (Join-Path $wt 'bench.ps1') -Encoding UTF8

# --- 4. venv ---------------------------------------------------------------
# Per-bench, not shared: ~6s warm, and sharing couples benches together.
# NOTE: bare `uv venv` grabs CPython 3.14.7 and dies; --python 3.13 fails the
# same way; the WindowsApps shim gives ModuleNotFoundError. Use the exact
# invocation recorded in fleet.json.uvVenvCommand.
if (-not $SkipVenv) {
  Push-Location $wt
  try {
    if (-not $cfg.uvVenvCommand) {
      throw 'fleet.json has no uvVenvCommand. Record the working `uv venv` invocation there first.'
    }
    Invoke-Expression $cfg.uvVenvCommand
    uv pip install -r requirements.txt -r requirements-dev.txt -r requirements-server.txt
    uv pip install pygame   # requirements-pi.txt omits it (apt on the Pi), but
                            # tests/pi/display/test_hdmi_render.py imports it unguarded
  } finally { Pop-Location }
}

# --- 5. lease + context ----------------------------------------------------
New-Item -ItemType Directory -Path (Join-Path $wt '.fleet') -Force | Out-Null
@{
  role = $Role; ticket = $Ticket; slug = $Slug; branch = $branch
  surface = $Surface; share = $cfg.share; leasedAt = (Get-Date -Format s)
} | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $wt '.fleet\lease.json') -Encoding UTF8

# Bench notes go to CLAUDE.local.md, NEVER to CLAUDE.md. CLAUDE.md is tracked:
# writing it made every bench start dirty, cost the agent the 373 lines of real
# project instructions, and left the clobbered file one `git add CLAUDE.md` away
# from reaching dev. CLAUDE.local.md is auto-loaded the same way and is ignored.

# --- resolve the context imports, LOUDLY ------------------------------------
# An `@path` import that points at a missing file is silent: Claude Code loads
# nothing and the agent starts with no role context, looking normal. So resolve
# and assert here, at lease time, where the operator is watching.
$imports = @("$($cfg.share)\CLAUDE.md")
if ($Role -ne 'Integrator') {
  $rel = $roleContext[$Role]
  if (-not $rel) { throw "No context file mapped for role '$Role'. Add it to `$roleContext in this script." }
  $ctx = Join-Path "$($cfg.share)\offices" $rel
  if (-not (Test-Path $ctx)) {
    throw "Role context file missing: $ctx`nThe bench would boot with no charter and no warning. Fix the share or the `$roleContext map before leasing."
  }
  $imports += $ctx
}
# handbook.md is NOT auto-imported -- see the note in CLAUDE.local.md.
# Baseline text is GENERATED from this project's baseline.json. Hardcoding another
# project's counts sends every bench chasing phantom regressions.
$bjPath = Join-Path $ProjectRoot 'baseline.json'
if (Test-Path $bjPath) {
  $bj = Get-Content $bjPath -Raw | ConvertFrom-Json
  $r  = $bj.result
  $baselineNote = "Expected here: $($r.failed) failed / $($r.passed) passed / $($r.skipped) skipped / $($r.xfailed) xfailed.`nAuthoritative counts and provenance: $bjPath"
  if (($bj.PSObject.Properties.Name -contains 'WARNING_time_dependent') -and $bj.WARNING_time_dependent) { $baselineNote += "`n`nWARNING: this suite is NOT time-invariant -- $($bj.WARNING_time_dependent.summary) Compare only runs captured in the same state." }
} else {
  $baselineNote = "No baseline.json at $bjPath. Capture one before claiming a regression."
}

$wipTicket = "$($cfg.share)\board\wip\$Ticket.md"
if (-not (Test-Path $wipTicket)) {
  Write-Warning "No ticket file at $wipTicket -- creating a stub so the import is not dangling."
  New-Item -ItemType Directory -Path (Split-Path $wipTicket) -Force | Out-Null
  "# Ticket $Ticket`n`n(stub created at lease time -- no board item existed.)`n" |
    Set-Content $wipTicket -Encoding UTF8
}
$imports += $wipTicket
foreach ($i in $imports) { if (-not (Test-Path $i)) { throw "Import target missing: $i" } }
$importBlock = ($imports | ForEach-Object { "@$_" }) -join "`n"
@"
# Bench: $name

$importBlock

> handbook.md is deliberately NOT auto-imported -- read it on demand at
> `$($cfg.share)\offices\_shared\handbook.md`. It defines the cross-office
> procedures (hello / closeout / housekeeping). Follow the git contract in
> this file, not any git model described elsewhere.

## Your lease
- Branch ``$branch``. You are on it and you stay on it.
- Surface you may edit: $($Surface -join ', ')
- Run ``.\bench.ps1`` first. It sets PYTHONUTF8, FLEET_SHARE, OBD2_REPO_ROOT
  and activates the venv. Tests behave incorrectly without it.

## Baseline
GREEN IS NOT THE TARGET. This suite carries a large pre-existing failure set, so a
raw red/green read carries NO regression signal.

$baselineNote

Diff NODE IDS against the baseline, not totals:
    ... --tb=no -q | grep '^FAILED ' | sed 's/^FAILED //' | sort > actual.txt
    comm -13 baseline_ids.txt actual.txt   # <- YOUR regression. Fix it.
    comm -23 baseline_ids.txt actual.txt   # <- newly passing. Report it.
A count that differs is YOURS until you have accounted for it by name. Watch the
skip count too: +1 passed / -1 skipped is a signal.

## Finishing
    git add <explicit paths>          # never -A, never .
    git commit -m "${Ticket}: <what>"
    git fetch origin
    git merge origin/$($cfg.trunkBranch)     # resolve conflicts HERE, not in trunk
then move ``$($cfg.share)\board\wip\$Ticket.md`` to ``board\review\`` and stop.
You do not merge to $($cfg.trunkBranch). The integrator does.
"@ | Set-Content (Join-Path $wt 'CLAUDE.local.md') -Encoding UTF8

# The bench must start on a clean tree. A dirty status is how an agent talks
# itself into `git add -A`, and the surface check at merge needs status to mean
# something. Fail the lease here rather than let the agent discover it later.
Push-Location $wt
try {
  $dirty = git status --porcelain
  if ($dirty) {
    throw "Bench provisioned dirty -- git status is not clean:`n$($dirty -join "`n")"
  }
} finally { Pop-Location }

$wip = Join-Path $cfg.share "board\wip\$Ticket.md"
if (-not (Test-Path $wip)) {
  New-Item -ItemType Directory -Path (Split-Path $wip) -Force | Out-Null
@"
# $Ticket — $Slug

- role:     $Role
- branch:   $branch
- worktree: $wt
- surface:
$( ($Surface | ForEach-Object { "  - $_" }) -join "`n" )

## Goal

## Done when
"@ | Set-Content $wip -Encoding UTF8
}

Write-Host "`nLeased $wt" -ForegroundColor Green
Write-Host "  branch  : $branch"
Write-Host "  surface : $($Surface -join ', ')"
Write-Host "  start   : cd $wt ; .\bench.ps1 ; claude"
if ($Launch) { Push-Location $wt; & (Join-Path $wt 'bench.ps1'); claude; Pop-Location }
