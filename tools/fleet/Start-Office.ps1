<#
.SYNOPSIS
  Prepare and enter an agent office. The office equivalent of a bench's bench.ps1.

.DESCRIPTION
  Benches get their environment from the bench.ps1 that New-Bench writes. Offices
  had no equivalent, so an office session started by hand inherited the SHARED
  user config -- the same cross-project leak that CLAUDE_CONFIG_DIR closes for
  benches. An office session is the one most people actually run, so it needs it
  more, not less.

  Sets:
    CLAUDE_CONFIG_DIR  per-project, so settings/history/hooks do not leak sideways
    FLEET_SHARE        the offices root, for tools/_paths.py
    FLEET_ROLE         this office's slug, so the git guard knows who is acting
    PYTHONUTF8         1 -- Windows defaults to cp1252 and mangles charter text

.EXAMPLE
  .\Start-Office.ps1 -Role pm
  .\Start-Office.ps1 -Role drpixel -Launch
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Role,
  [string]$FleetJson,
  [switch]$Launch
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'FleetRoles.ps1')

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

$cfg     = Get-Content $FleetJson -Raw | ConvertFrom-Json
$offices = Join-Path $cfg.share 'offices'
$roles   = Get-FleetRoles -Cfg $cfg -OfficesRoot $offices
$rec     = $roles | Where-Object { $_.slug -eq $Role } | Select-Object -First 1
if (-not $rec) {
  throw "Unknown office '$Role'. This project has: $((($roles | ForEach-Object { $_.slug }) -join ', '))"
}

$officeDir = Join-Path $offices $Role
if (-not (Test-Path $officeDir)) { throw "Office directory missing: $officeDir" }
foreach ($required in 'CLAUDE.md','CHARTER.md') {
  if (-not (Test-Path (Join-Path $officeDir $required))) {
    throw "$Role is missing $required. An office boots from CLAUDE.md; without it the agent starts with no identity."
  }
}

# Per-project config: created/repaired here so an office session is isolated the
# same way a bench is.
& (Join-Path $PSScriptRoot 'Initialize-ProjectConfig.ps1') -FleetJson $FleetJson | Out-Null

$projectDir = Split-Path $FleetJson -Parent
$env:CLAUDE_CONFIG_DIR = Join-Path $projectDir '.claude-config'
$env:FLEET_SHARE       = $offices
$env:FLEET_ROLE        = $Role
$env:PYTHONUTF8        = '1'

Set-Location $officeDir

Write-Host ""
Write-Host "  Office : $Role" -ForegroundColor Cyan
Write-Host "  Agent  : $(if ($rec.persona) { $rec.persona } else { '(persona not declared in fleet.json)' })  [$($rec.archetype), $($rec.mode)]"
Write-Host "  Path   : $officeDir"
Write-Host "  Config : $env:CLAUDE_CONFIG_DIR" -ForegroundColor DarkGray
Write-Host "  Skills : $((Get-ChildItem (Join-Path $officeDir '.claude\skills') -Directory -EA SilentlyContinue | ForEach-Object { $_.Name }) -join ', ')" -ForegroundColor DarkGray
Write-Host ""
if ($rec.mode -eq 'headless') {
  Write-Host "  NOTE: this office is declared headless. Nothing will answer a prompt." -ForegroundColor Yellow
}
Write-Host "  Start with:  claude        then run the 'hello' skill" -ForegroundColor Green
Write-Host ""

if ($Launch) { claude }
