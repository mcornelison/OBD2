<#
.SYNOPSIS
  Push the repo's skill and command masters into each office, or report drift.

.DESCRIPTION
  Claude Code discovers skills and commands under <cwd>/.claude/, walking up only
  to a git root. The share is NOT a git root, so an office without its own copy has
  NONE. Before offices moved out of the repo this was masked: proximity did the
  work, and moving the tree removed it silently.

  Two kinds of master, deliberately different:

    SKILLS    .claude\skills\<name>\SKILL.md -- GENERIC. Byte-identical in every
              office of every project. They use relative paths, because an agent's
              working directory IS its office. Model-invoked, so they work for a
              HEADLESS agent with no user present to type anything.

    COMMANDS  .claude\commands\<verb>-<slug>.md -- per-office, user-invoked.
              Reserved for procedures that genuinely differ by office (a PM's
              sprint ceremonies) rather than for the universal set.

  THE ROSTER IS NEVER HARDCODED -- it comes from FleetRoles.ps1.
  -Check reports drift and EXITS NON-ZERO.
#>
[CmdletBinding()]
param([switch]$Check, [string]$FleetJson)

$ErrorActionPreference = 'Stop'

if (-not $FleetJson) {
  $probe = $PSScriptRoot
  while ($probe) {
    $c = Join-Path $probe 'fleet.json'
    if (Test-Path $c) { $FleetJson = $c; break }
    $parent = Split-Path $probe -Parent
    if (-not $parent -or $parent -eq $probe) { break }
    $probe = $parent
  }
}
if (-not $FleetJson -or -not (Test-Path $FleetJson)) { throw "fleet.json not found above $PSScriptRoot. Pass -FleetJson." }

$fleet   = Get-Content $FleetJson -Raw | ConvertFrom-Json
. (Join-Path $PSScriptRoot 'FleetRoles.ps1')
$offices = Join-Path $fleet.share 'offices'
$roles   = @((Get-FleetRoles -Cfg $fleet -OfficesRoot $offices) | ForEach-Object { $_.slug })

# Command masters are matched by filename suffix "*-<slug>.md". A project whose
# master is named for an ABBREVIATION -- init-arch.md for the 'architect' office,
# init-uidev.md for 'uideveloper' -- matches NOTHING, so that office's commands sit
# outside drift detection entirely and -Check stays green about them. That is the
# same failure this script already guards at the coarse level ("a clean report here
# would be a false green"), one layer down.
#
# Aliases are declared per role in fleet.json (roles[].commandAliases), so the
# roster stays the SSOT and no abbreviation is hardcoded here. Read from the raw
# config rather than the normalised records, which carry only the four axes.
$aliasMap = @{}
if ($fleet.PSObject.Properties.Name -contains 'roles') {
  foreach ($r in @($fleet.roles)) {
    if ($r -is [string]) { continue }
    if (($r.PSObject.Properties.Name -contains 'commandAliases') -and $r.commandAliases) {
      $aliasMap[$r.slug] = @($r.commandAliases)
    }
  }
}
$suffixes = @{}
foreach ($sl in $roles) {
  $set = @($sl)
  if ($aliasMap.ContainsKey($sl)) { $set += @($aliasMap[$sl]) }
  $suffixes[$sl] = @($set | Sort-Object -Unique)
}
$matchedMasters = New-Object System.Collections.Generic.HashSet[string]

$skillSrc = Join-Path $fleet.trunk '.claude\skills'
$cmdSrc   = Join-Path $fleet.trunk '.claude\commands'
if (-not (Test-Path $offices)) { throw "Offices dir not found: $offices" }
if (-not $roles -or $roles.Count -eq 0) { throw "No roles resolved. Declare them in fleet.json, or give each office a charter and .claude\commands\." }

$drift = 0; $synced = 0; $officesSeen = 0

function Sync-One($srcFile, $dstFile, $label, $role) {
  $exists = Test-Path $dstFile
  $same   = $exists -and ((Get-FleetFileHash $srcFile) -eq (Get-FleetFileHash $dstFile))
  if ($same) { return }
  if ($script:Check) {
    $what = if ($exists) { 'DRIFTED' } else { 'MISSING' }
    Write-Host ("{0,-12} {1,-8} {2}" -f $role, $what, $label) -ForegroundColor Yellow
    $script:drift++
  } else {
    New-Item -ItemType Directory -Force -Path (Split-Path $dstFile) | Out-Null
    Copy-Item $srcFile $dstFile -Force
    Write-Host ("{0,-12} synced   {1}" -f $role, $label) -ForegroundColor Green
    $script:synced++
  }
}
$script:Check = $Check; $script:drift = 0; $script:synced = 0

foreach ($role in $roles | Sort-Object) {
  $officeDir = Join-Path $offices $role
  if (-not (Test-Path $officeDir)) { Write-Warning "No office dir: $officeDir"; continue }
  $officesSeen++

  # 1. skills -- generic, identical everywhere
  if (Test-Path $skillSrc) {
    foreach ($sk in Get-ChildItem $skillSrc -Directory) {
      $src = Join-Path $sk.FullName 'SKILL.md'
      if (-not (Test-Path $src)) { continue }
      Sync-One $src (Join-Path $officeDir ".claude\skills\$($sk.Name)\SKILL.md") "skill:$($sk.Name)" $role
    }
  }

  # 2. commands -- only masters that actually target THIS office
  if (Test-Path $cmdSrc) {
    foreach ($sfx in $suffixes[$role]) {
      foreach ($m in Get-ChildItem $cmdSrc -Filter "*-$sfx.md" -File) {
        [void]$matchedMasters.Add($m.Name)
        Sync-One $m.FullName (Join-Path $officeDir ".claude\commands\$($m.Name)") "cmd:$($m.Name)" $role
      }
    }
  }
}

if ($officesSeen -eq 0) {
  Write-Host "FAILED: resolved $($roles.Count) role(s) but found NO office directories." -ForegroundColor Red
  Write-Host "A clean report here would be a false green -- nothing was examined." -ForegroundColor Red
  exit 1
}

# A master matching NO office is invisible to drift detection: it is never synced
# and never reported, so it looks fine forever. Name them. Some are legitimately
# trunk-only (an integrator or operator command that no office owns) -- this is a
# report, not an error, but it must not be silent.
if (Test-Path $cmdSrc) {
  $orphans = @(Get-ChildItem $cmdSrc -Filter *.md -File |
               Where-Object { -not $matchedMasters.Contains($_.Name) } |
               ForEach-Object { $_.Name })
  if ($orphans) {
    Write-Host ""
    Write-Host "Masters matching no office (trunk-only, or a missing commandAliases entry):" -ForegroundColor DarkGray
    $orphans | Sort-Object | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
  }
}

Write-Host ""
if ($Check) {
  if ($script:drift) { Write-Host "DRIFT: $($script:drift) file(s)" -ForegroundColor Red; exit 1 }
  Write-Host "No drift across $officesSeen office(s). Roster: $($roles -join ', ')" -ForegroundColor Green
  exit 0
}
Write-Host "Synced $($script:synced) file(s) across $officesSeen office(s). Roster: $($roles -join ', ')" -ForegroundColor Green
