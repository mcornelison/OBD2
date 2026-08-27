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
  [Parameter(Mandatory)][ValidateSet('architect','pm','ralph','tester','tuner','uideveloper','Integrator')]
  [string]$Role,
  [Parameter(Mandatory)][string]$Ticket,
  [Parameter(Mandatory)][string]$Slug,
  [string[]]$Surface  = @('**'),
  [string]$ProjectRoot = 'C:\agents\OBD2v3',
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
$roleContext = @{
  architect  = 'architect\claude.md'
  pm         = 'pm\claude.md'
  ralph      = 'ralph\claude.md'
  tester     = 'tester\claude.md'
  tuner      = 'tuner\claude.md'
  uideveloper = 'uideveloper\claude.md'
}

$cfg = Get-Content (Join-Path $ProjectRoot 'fleet.json') -Raw | ConvertFrom-Json

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

# --- 2. stamps -------------------------------------------------------------
# A worktree gets TRACKED files only. These are gitignored and required.
New-Item -ItemType Directory -Path (Join-Path $wt 'deploy') -Force | Out-Null
Copy-Item (Join-Path $stamp '.env')                  (Join-Path $wt '.env') -Force
Copy-Item (Join-Path $stamp 'deploy\deploy.conf')    (Join-Path $wt 'deploy\deploy.conf') -Force
Copy-Item (Join-Path $stamp '.superpowers')          (Join-Path $wt '.superpowers') -Recurse -Force

foreach ($f in @('.env','deploy\deploy.conf')) {
  $a = (Get-FileHash (Join-Path $stamp $f) -Algorithm MD5).Hash
  $b = (Get-FileHash (Join-Path $wt    $f) -Algorithm MD5).Hash
  if ($a -ne $b) { throw "Stamp mismatch on $f" }
}

# --- 3. environment --------------------------------------------------------
# PYTHONUTF8: without it, 34 tests fail with UnicodeDecodeError on cp1252 and
#   look exactly like real breakage.
# FLEET_SHARE: tools/pm/_paths.py raises without it. That raise is deliberate --
#   the silent-fallback version read stale data in trunk and worked nowhere else.
@"
`$env:PYTHONUTF8 = '1'
`$env:FLEET_SHARE = '$($cfg.share)\offices'
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

> handbook.md is deliberately NOT imported. It is 657 lines, and its
> per-agent-clone section still hands you a table of `Z:\o\OBD2v2-<role>` paths
> -- the FROZEN ARCHIVE. Read it if you need the A2AL message format
> ($($cfg.share)\offices\handbook.md, section 9); do not follow its git model.

## Your lease
- Branch ``$branch``. You are on it and you stay on it.
- Surface you may edit: $($Surface -join ', ')
- Run ``.\bench.ps1`` first. It sets PYTHONUTF8, FLEET_SHARE, OBD2_REPO_ROOT
  and activates the venv. Tests behave incorrectly without it.

## Baseline
GREEN IS NOT THE TARGET. 90 non-passing tests are EXPECTED here:
74 failed + 16 errors, out of 8041 collected. The 16 errors are 8 DockerException
(no Docker on this box) plus MariaDB-dependent contract tests.
See C:\agents\OBD2v3\baseline.json for the authoritative counts and for one
pending delta (skipped 52 -> 51) that is already explained there.
A count that differs is YOURS until you have accounted for it by name.
Diff the counts individually, not just the totals -- three real defects in this
project were caught by a count moving, not by anything turning red.

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
