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

# The fleet kit holds the GOVERNANCE templates -- the masters above the project's
# own masters. Sync-OfficeCommands has always enforced office <-> trunk. Nothing
# enforced trunk <-> kit, which is exactly how 'optimize-knowledge' came to differ
# between two projects and the kit with nobody noticing for a day.
# Resolved the same way Initialize-ProjectConfig resolves it, so there is one rule.
$kitRoot = $null
$kitField = $null
if ($fleet.PSObject.Properties.Name -contains 'fleetKit') { $kitField = $fleet.fleetKit }
foreach ($cand in @($env:FLEET_KIT, $kitField)) {
  if ($cand -and (Test-Path (Join-Path $cand 'templates\skills'))) { $kitRoot = $cand; break }
}

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
      # A skill is UNIVERSAL by default -- byte-identical in every office, which is
      # what lets one file serve every role. fleet.json 'skills' is the exception: a
      # skill named there goes ONLY to the offices listed. Without it an
      # office-specific skill cannot be governed at all, because promoting it to a
      # master would spray it into every office -- so it stays unmanaged instead.
      $onlyFor = $null
      if ($fleet.PSObject.Properties.Name -contains 'skills' -and $fleet.skills) {
        if ($fleet.skills.PSObject.Properties.Name -contains $sk.Name) { $onlyFor = @($fleet.skills.$($sk.Name)) }
      }
      if ($onlyFor -and ($onlyFor -notcontains $role)) { continue }
      Sync-One $src (Join-Path $officeDir ".claude\skills\$($sk.Name)\SKILL.md") "skill:$($sk.Name)" $role
    }
  }

  # 2. commands -- only masters that actually target THIS office
  if (Test-Path $cmdSrc) {
    # Two routing mechanisms, deliberately COMPOSED rather than chosen between:
    #   suffixes    -- the filename names the office or an alias of it
    #                  (init-arch.md -> architect). Handles abbreviations.
    #   'commands'  -- an explicit pattern list per office in fleet.json. Handles
    #                  masters whose filename names NO office at all
    #                  (groom-sprint.md, prd.md), which no suffix rule can match.
    # A master reached by either is routed, so adding the map to an existing
    # project is purely additive and disables nothing.
    $patterns = @($suffixes[$role] | ForEach-Object { "*-$_.md" })
    if ($fleet.PSObject.Properties.Name -contains 'commands' -and $fleet.commands) {
      if ($fleet.commands.PSObject.Properties.Name -contains $role) { $patterns += @($fleet.commands.$role) }
    }
    $seenHere = @{}
    foreach ($pat in ($patterns | Sort-Object -Unique)) {
      foreach ($m in Get-ChildItem $cmdSrc -Filter $pat -File -EA SilentlyContinue) {
        if ($seenHere.ContainsKey($m.Name)) { continue }
        $seenHere[$m.Name] = $true
        [void]$matchedMasters.Add($m.Name)
        Sync-One $m.FullName (Join-Path $officeDir ".claude\commands\$($m.Name)") "cmd:$($m.Name)" $role
      }
    }
  }
}

# ---- trunk masters vs the governance kit templates -------------------------
# REPORT ONLY. Updating a trunk master is a repo write and belongs in a bench, so
# this never copies -- it names the drift and the remedy. Silence here is the
# failure mode being closed: a project master that has quietly diverged from the
# fleet template looks identical to one that is in step.
$kitDrift = 0
if (-not $kitRoot) {
  Write-Host ""
  Write-Host "NOTE: no fleet kit resolved (set FLEET_KIT or add 'fleetKit' to fleet.json)." -ForegroundColor Yellow
  Write-Host "      Trunk masters were NOT checked against the governance templates." -ForegroundColor Yellow
} else {
  $tplRoot = Join-Path $kitRoot 'templates\skills'
  foreach ($tpl in Get-ChildItem $tplRoot -Directory -EA SilentlyContinue) {
    $t = Join-Path $tpl.FullName 'SKILL.md'
    if (-not (Test-Path $t)) { continue }
    $m = Join-Path $skillSrc "$($tpl.Name)\SKILL.md"
    if (-not (Test-Path $m)) {
      Write-Host ("kit-template  MISSING  skill:{0} (not in this project's trunk)" -f $tpl.Name) -ForegroundColor Yellow
      $kitDrift++
    } elseif ((Get-FleetFileHash $t) -ne (Get-FleetFileHash $m)) {
      Write-Host ("kit-template  DRIFTED  skill:{0}" -f $tpl.Name) -ForegroundColor Yellow
      $kitDrift++
    }
  }
  if ($kitDrift) {
    Write-Host ""
    Write-Host "$kitDrift skill master(s) differ from the fleet templates in $tplRoot" -ForegroundColor Yellow
    Write-Host "DRIFT HAS A DIRECTION. Diff before copying either way -- the project copy is" -ForegroundColor Yellow
    Write-Host "sometimes the newer and better one, and this tool cannot tell you which." -ForegroundColor Yellow
    Write-Host "To adopt the template: lease a bench, copy it into <trunk>\.claude\skills\," -ForegroundColor Yellow
    Write-Host "merge, then re-run this script without -Check to push it into every office." -ForegroundColor Yellow
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
# Skills present in an OFFICE that no master governs. The sync only pushes
# master -> office, so it cannot see these: it reports "no drift" while the copies
# drift freely. A WARNING, not drift -- with no master there is nothing to sync
# FROM, so the remedy is a human decision, and the office copy is often newer.
if (Test-Path $skillSrc) {
  $masterSkills = @(Get-ChildItem $skillSrc -Directory -EA SilentlyContinue | ForEach-Object { $_.Name })
  $ungoverned = @{}
  foreach ($r in $roles) {
    $osk = Join-Path (Join-Path $offices $r) '.claude\skills'
    if (-not (Test-Path $osk)) { continue }
    foreach ($d in Get-ChildItem $osk -Directory -EA SilentlyContinue) {
      if ($masterSkills -notcontains $d.Name) {
        if (-not $ungoverned.ContainsKey($d.Name)) { $ungoverned[$d.Name] = @() }
        $ungoverned[$d.Name] += $r
      }
    }
  }
  if ($ungoverned.Count) {
    Write-Host ""
    Write-Host "UNGOVERNED OFFICE SKILLS -- present in an office, no master in trunk:" -ForegroundColor Yellow
    foreach ($k in ($ungoverned.Keys | Sort-Object)) {
      Write-Host ("  {0,-28} {1}" -f $k, (($ungoverned[$k] | Sort-Object) -join ', ')) -ForegroundColor Yellow
    }
    Write-Host "Nothing enforces these copies. Promote one to $skillSrc (and scope it in" -ForegroundColor Yellow
    Write-Host "fleet.json 'skills' if it is office-specific), or remove them." -ForegroundColor Yellow
  }
}

# A 'skills' or 'commands' entry naming a role or master that does not exist is a
# silent no-op -- the same class of failure the routing was added to end.
foreach ($mapName in @('skills','commands')) {
  if (-not ($fleet.PSObject.Properties.Name -contains $mapName) -or -not $fleet.$mapName) { continue }
  $bad = @()
  foreach ($p in $fleet.$mapName.PSObject.Properties) {
    if ($mapName -eq 'skills') {
      if (-not (Test-Path (Join-Path $skillSrc $p.Name))) { $bad += "$($p.Name): no master under $skillSrc" }
      foreach ($r in @($p.Value)) { if ($roles -notcontains $r) { $bad += "$($p.Name) -> '$r' is not a role" } }
    } else {
      if ($roles -notcontains $p.Name) { $bad += "'$($p.Name)' is not a role" }
    }
  }
  if ($bad.Count) {
    Write-Host ""
    Write-Host "BAD '$mapName' ROUTING in fleet.json:" -ForegroundColor Red
    $bad | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    $script:drift += $bad.Count
  }
}

if (Test-Path $cmdSrc) {
  $orphans = @(Get-ChildItem $cmdSrc -Filter *.md -File |
               Where-Object { -not $matchedMasters.Contains($_.Name) } |
               ForEach-Object { $_.Name })
  if ($orphans) {
    Write-Host ""
    # Yellow, not DarkGray: this is the failure that hid six PM commands in one
    # project for months. Still NOT drift -- some masters are legitimately
    # trunk-only (an integrator or operator command no office owns), and failing
    # on those would teach everyone to ignore the check.
    Write-Host "MASTERS MATCHING NO OFFICE (trunk-only, or a missing commandAliases / 'commands' entry):" -ForegroundColor Yellow
    $orphans | Sort-Object | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
  }
}

Write-Host ""
if ($Check) {
  if ($script:drift -or $kitDrift) {
    if ($script:drift) { Write-Host "DRIFT: $($script:drift) office file(s)" -ForegroundColor Red }
    if ($kitDrift)     { Write-Host "DRIFT: $kitDrift trunk master(s) vs fleet templates" -ForegroundColor Red }
    exit 1
  }
  Write-Host "No drift across $officesSeen office(s). Roster: $($roles -join ', ')" -ForegroundColor Green
  exit 0
}
Write-Host "Synced $($script:synced) file(s) across $officesSeen office(s). Roster: $($roles -join ', ')" -ForegroundColor Green
