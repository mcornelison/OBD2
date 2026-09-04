<#
.SYNOPSIS
  One entry point for fleet work. Run `fleet.ps1` with no arguments for help.

.DESCRIPTION
  This is a DISPATCHER, not an implementation. Every command below hands off to
  the script that already does the job -- New-Bench.ps1, Invoke-FleetMerge.ps1 --
  so there is exactly one implementation of each and one place to look for it.

  It exists because agents kept losing time to the same four questions:

    "Where are the scripts?"        -- they were at an undocumented path
    "Do I even need a bench?"       -- not for share-only work; nothing said so
    "What is -Ticket?"              -- a lease label, not a user story number
    "Is my venv broken?"            -- it was uv, not the venv; different question

  `fleet.ps1 doctor` answers all four against the machine in front of you rather
  than against documentation that may have drifted.

.EXAMPLE
  .\fleet.ps1 doctor
  .\fleet.ps1 status
  .\fleet.ps1 bench -Role tuner -Ticket TUNER-003 -Slug coolant-band -Surface "specs/**"
  .\fleet.ps1 merge
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)][string]$Command,
  [Parameter(ValueFromRemainingArguments = $true)]$Rest
)

$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot

function Say  ($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Ok   ($m) { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Bad  ($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

# --- locate the project by walking up for fleet.json -------------------------
# Depth-independent on purpose. A fixed number of parent hops is the bug that put
# the old resolver ABOVE the repo root after the tree moved.
function Find-FleetJson {
  $d = Get-Item $Here
  while ($d) {
    $c = Join-Path $d.FullName 'fleet.json'
    if (Test-Path $c) { return $c }
    $d = $d.Parent
  }
  return $null
}

$fleetJsonPath = Find-FleetJson
$cfg = if ($fleetJsonPath) { Get-Content $fleetJsonPath -Raw | ConvertFrom-Json } else { $null }

function Show-Help {
  Say ""
  Say "fleet.ps1 -- one entry point for fleet work" 'Cyan'
  Say ""
  Say "  doctor                 check this machine and say what is actually wrong"
  Say "  status                 leased benches, board lanes, trunk position"
  Say "  bench   <args>         lease a bench   -> New-Bench.ps1"
  Say "  merge   [args]         run the integrator -> Invoke-FleetMerge.ps1"
  Say "  paths                  print the resolved paths from fleet.json"
  Say ""
  Say "Lease a bench:" 'Cyan'
  Say "  .\fleet.ps1 bench -Role <role> -Ticket <label> -Slug <slug> -Surface <globs>"
  Say ""
  Say "  -Ticket is a LEASE LABEL, not a user story number. It names the bench" 'DarkGray'
  Say "  directory and branch. Do not mint one from the PM's story counter." 'DarkGray'
  Say ""
  Say "You do NOT need a bench to edit your own office." 'Yellow'
  Say "  Offices live on the share and are not under git. Edit them in place." 'DarkGray'
  Say "  Lease a bench only to change files in the REPO." 'DarkGray'
  Say ""
}

function Invoke-Sub($script, $arguments) {
  $p = Join-Path $Here $script
  if (-not (Test-Path $p)) {
    Bad "$script is not next to fleet.ps1 ($Here)."
    Say "  Fleet tooling is meant to live together in tools/fleet/ inside the repo."
    Say "  If it is missing here, the repo was cloned without it -- check that"
    Say "  .gitignore has an exception for tools/fleet/ and that the files are tracked."
    exit 1
  }
  & $p @arguments
  exit $LASTEXITCODE
}

switch -Regex ($Command) {

  '^(paths)$' {
    if (-not $cfg) { Bad "No fleet.json found walking up from $Here"; exit 1 }
    Say "`nfleet.json: $fleetJsonPath" 'Cyan'
    $cfg.PSObject.Properties |
      Where-Object { $_.Value -is [string] } |
      ForEach-Object { "  {0,-14} {1}" -f $_.Name, $_.Value }
    exit 0
  }

  '^(status)$' {
    if (-not $cfg) { Bad "No fleet.json found walking up from $Here"; exit 1 }
    Say "`n=== Trunk ===" 'Cyan'
    git --git-dir=$($cfg.bare) --work-tree=$($cfg.trunk) log --oneline -1 2>$null | ForEach-Object { "  $_" }

    Say "`n=== Leased benches ===" 'Cyan'
    $any = $false
    Get-ChildItem $cfg.worktrees -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      $any = $true
      $lease = Join-Path $_.FullName '.fleet\lease.json'
      $venv  = Test-Path (Join-Path $_.FullName '.venv\Scripts\python.exe')
      if (Test-Path $lease) {
        $l = Get-Content $lease -Raw | ConvertFrom-Json
        "  {0,-46} ticket {1,-12} surface {2}" -f $_.Name, $l.ticket, ($l.surface -join ',')
        # US-676: the PRESENCE of a lease used to be read as proof of a good
        # lease. It is not -- New-Bench.ps1 now writes the lease first and stamps
        # the verdict last, so a half-built bench has a lease that says so.
        # A lease with no `provisioning` field predates that and is left alone:
        # flagging every bench leased before this shipped is the false positive
        # that teaches everyone to ignore the warning.
        $prov = if ($l.PSObject.Properties.Name -contains 'provisioning') { $l.provisioning } else { $null }
        if ($prov -and $prov -ne 'complete') {
          Bad  "  ^ PROVISIONING INCOMPLETE (failed at step '$($l.failedStep)') -- NOT mergeable"
          Say  "        see $($_.FullName)\.fleet\PROVISIONING-INCOMPLETE.md" 'DarkGray'
        }
        if (-not $venv) { Warn "  ^ no .venv -- tests cannot run in this bench" }
      } else {
        Warn "$($_.Name) has NO .fleet\lease.json -- the integrator will SKIP it"
        Say  "        (hand-made worktrees are invisible to merge; lease via 'fleet.ps1 bench')" 'DarkGray'
      }
    }
    if (-not $any) { Say "  (none)" }

    Say "`n=== Board ===" 'Cyan'
    foreach ($lane in 'backlog','wip','review','done') {
      $p = Join-Path $cfg.share "board\$lane"
      $n = (Get-ChildItem $p -File -ErrorAction SilentlyContinue).Count
      "  {0,-10} {1}" -f $lane, $n
    }
    exit 0
  }

  '^(doctor|check)$' {
    Say "`n=== fleet doctor ===" 'Cyan'

    if ($cfg) { Ok "project: $($cfg.project)  (fleet.json at $fleetJsonPath)" }
    else { Bad "no fleet.json found walking up from $Here"; Say "  Run this from inside a project."; exit 1 }

    # --- tooling present and together -------------------------------------
    foreach ($s in 'New-Bench.ps1','Invoke-FleetMerge.ps1') {
      if (Test-Path (Join-Path $Here $s)) { Ok "tooling: $s" }
      else { Bad "tooling: $s MISSING from $Here" }
    }

    # --- FLEET_SHARE: absent is NORMAL, say so plainly --------------------
    if ($env:FLEET_SHARE) { Ok "FLEET_SHARE set: $env:FLEET_SHARE" }
    else {
      Ok "FLEET_SHARE not set -- this is EXPECTED in an office session, not a fault."
      Say "         It is exported by a bench's bench.ps1. Paths come from fleet.json." 'DarkGray'
    }

    # --- bare HEAD: the silent branch-leak ---------------------------------
    $head = git --git-dir=$($cfg.bare) symbolic-ref HEAD 2>$null
    if ($head -eq "refs/heads/$($cfg.trunkBranch)") { Ok "bare HEAD -> $head" }
    else {
      Bad "bare HEAD is '$head' but trunkBranch is '$($cfg.trunkBranch)'"
      Say "         'git branch -d' judges 'merged' against HEAD and will refuse EVERY" 'DarkGray'
      Say "         merged branch. Fix: git --git-dir=$($cfg.bare) symbolic-ref HEAD refs/heads/$($cfg.trunkBranch)" 'DarkGray'
    }

    # --- venv vs uv: DIFFERENT questions ----------------------------------
    $venvPy = Join-Path $cfg.trunk '.venv\Scripts\python.exe'
    if (Test-Path $venvPy) {
      $v = & $venvPy -V 2>&1
      Ok "trunk venv runs: $v"
      # "It runs" is not "it works". A bare `uv venv` produces an EMPTY
      # environment that starts perfectly and cannot run a single test. Trunk's
      # venv was silently rebuilt on 2026-08-27; it kept its packages, but the
      # check that would have told us either way did not exist.
      $null = & $venvPy -c "import pytest" 2>&1
      if ($LASTEXITCODE -eq 0) { Ok "trunk venv has its dependencies" }
      else {
        Bad "trunk venv is EMPTY -- it starts, but no test can run"
        Say "         Reinstall: uv pip install --python <venv python> -r requirements.txt -r requirements-dev.txt" 'DarkGray'
      }
    } else { Warn "trunk has no .venv (fine if this is not a Python project)" }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
      $probe = Join-Path $env:TEMP ("fleet-uv-probe-" + [guid]::NewGuid().ToString('N').Substring(0,8))
      # uv writes progress to STDERR even on success. With $ErrorActionPreference
      # = 'Stop' that becomes a terminating error, so a PASSING probe printed a
      # red NativeCommandError. Relax it for the probe and judge by exit code.
      $prev = $ErrorActionPreference
      $ErrorActionPreference = 'Continue'
      $null = & uv venv --python 3.13 $probe 2>&1
      $uvExit = $LASTEXITCODE
      $ErrorActionPreference = $prev
      if ($uvExit -eq 0) { Ok "uv can create a venv (new benches will provision)" }
      else {
        Bad "uv CANNOT create a venv -- new benches will come up without one"
        Say "         This is SEPARATE from the venv above: the gate can pass while" 'DarkGray'
        Say "         every new bench is broken. Usual cause: a minor-version symlink" 'DarkGray'
        Say "         in %APPDATA%\uv\python with a POSIX target. Delete THAT LINK ONLY --" 'DarkGray'
        Say "         deleting the whole store breaks the venv that still works." 'DarkGray'
      }
      Remove-Item $probe -Recurse -Force -ErrorAction SilentlyContinue
    } else { Warn "uv not on PATH (fine if this is not a Python project)" }

    # --- stray worktrees the integrator would skip -------------------------
    $stray = Get-ChildItem $cfg.worktrees -Directory -ErrorAction SilentlyContinue |
             Where-Object { -not (Test-Path (Join-Path $_.FullName '.fleet\lease.json')) }
    if ($stray) { foreach ($s in $stray) { Bad "bench without a lease: $($s.Name) -- merge will SKIP it silently" } }
    else { Ok "every bench carries a lease" }

    Say "`nRun 'fleet.ps1 status' for what is currently leased.`n" 'Cyan'
    exit 0
  }

  '^(bench|new-bench|lease)$' { Invoke-Sub 'New-Bench.ps1' $Rest }

  '^(merge|integrate)$' {
    if ($Rest -and $Rest.Count) { Invoke-Sub 'Invoke-FleetMerge.ps1' $Rest }
    else { Invoke-Sub 'Invoke-FleetMerge.ps1' @() }
  }

  default { Show-Help; if ($Command) { Bad "unknown command: $Command"; exit 1 }; exit 0 }
}
