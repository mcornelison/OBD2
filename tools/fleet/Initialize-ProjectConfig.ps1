<#
.SYNOPSIS
  Create/repair a per-project CLAUDE_CONFIG_DIR. Idempotent; run it before every
  bench launch.

.DESCRIPTION
  The user-level config dir is read by EVERY agent in EVERY project, so it is both
  a leak path and a collision surface. Pointing CLAUDE_CONFIG_DIR at a per-project
  directory isolates settings, session state and history.

  ISOLATION IS TOTAL -- the isolated dir inherits NOTHING. Two things must be seeded
  or the bench is broken in ways that do not announce themselves:

    1. .credentials.json  -- without it: "Not logged in - Please run /login",
       exit 1. A headless agent cannot log in.
    2. settings.json      -- hooks live here. Without it the git guard and the
       config guard SILENTLY DO NOT RUN. Verified: a hook seeded into an isolated
       config dir does fire; with no settings.json there are no hooks at all.

  Credentials are HARDLINKED, not copied, so a token refresh in any project
  propagates to all of them. If the CLI ever replaces the file (write-temp-rename)
  the link breaks; this script detects divergence and re-links, so running it at
  every bench launch self-heals.
#>
[CmdletBinding()]
param([string]$FleetJson, [switch]$Check)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'FleetRoles.ps1')   # Get-FleetFileHash lives there

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

$cfg        = Get-Content $FleetJson -Raw | ConvertFrom-Json
$projectDir = Split-Path $FleetJson -Parent
$cfgDir     = Join-Path $projectDir '.claude-config'
$userCfg    = Join-Path $env:USERPROFILE '.claude'
$userCreds  = Join-Path $userCfg '.credentials.json'
$projCreds  = Join-Path $cfgDir '.credentials.json'
# Hook root must NOT be derived from this script's position: this file is copied
# into <trunk>\tools\fleet\, where a relative walk yields a directory that does
# not exist -- and a settings.json pointing at a missing hook fails SILENTLY.
$fleetKitField = $null
if ($cfg.PSObject.Properties.Name -contains 'fleetKit') { $fleetKitField = $cfg.fleetKit }
$hookRoot = $null
foreach ($cand in @(
    $env:FLEET_KIT,
    (Split-Path $PSScriptRoot -Parent),
    $fleetKitField,
    'Z:\Project-Governance\fleet-kit'
  )) {
  if ($cand -and (Test-Path (Join-Path $cand 'hooks\git-guard.ps1'))) { $hookRoot = $cand; break }
}
if (-not $hookRoot) {
  throw "Fleet kit not found. Set FLEET_KIT, or add 'fleetKit' to fleet.json. Looked for hooks\git-guard.ps1."
}

$issues = @()

if (-not (Test-Path $cfgDir)) {
  if ($Check) { $issues += "config dir missing: $cfgDir" }
  else { New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null; Write-Host "  created $cfgDir" -ForegroundColor Green }
}

# ---- credentials -----------------------------------------------------------
if (-not (Test-Path $userCreds)) {
  throw "No credentials at $userCreds. Log in once at user scope first; this script only links them."
}
$needLink = $true
if (Test-Path $projCreds) {
  $same = (Get-FleetFileHash $userCreds) -eq (Get-FleetFileHash $projCreds)
  if ($same) { $needLink = $false }
  else { $issues += "credentials DIVERGED from user scope (link was broken by a rewrite)" }
}
else { $issues += "credentials missing" }

if ($needLink -and -not $Check) {
  if (Test-Path $projCreds) { Remove-Item $projCreds -Force }
  try {
    New-Item -ItemType HardLink -Path $projCreds -Target $userCreds -EA Stop | Out-Null
    Write-Host "  credentials hardlinked (a refresh in any project propagates)" -ForegroundColor Green
  } catch {
    Copy-Item $userCreds $projCreds -Force
    Write-Warning "  hardlink failed; COPIED instead. A token refresh will NOT propagate -- re-run this script if auth starts failing."
  }
}

# ---- settings.json: hooks are the part that fails silently -----------------
$settingsPath = Join-Path $cfgDir 'settings.json'
$projSettings = Join-Path $cfg.trunk '.claude\settings.json'
$allow = @()
if (Test-Path $projSettings) {
  $ps = Get-Content $projSettings -Raw | ConvertFrom-Json
  if ($ps.permissions -and $ps.permissions.allow) { $allow = @($ps.permissions.allow) }
}
# EVERY nested hashtable must be [ordered]. A plain @{} is an unordered
# Hashtable whose enumeration order varies BETWEEN PROCESSES, so ConvertTo-Json
# emitted 'matcher' and 'hooks' in a different order on each run -- and the
# comparison below is whole-file TEXT. The result: -Check reported
# "settings.json missing or drifted (hooks would not run)" on a file this script
# had just written itself, with identical content and identical length (1710
# chars both sides; only key order differed). Observed 8 failures out of 9 runs
# against a byte-identical file.
#
# A guard that cries drift at unchanged config is worse than no guard: it is the
# false positive that teaches everyone to ignore the check, and this one gates
# whether an agent's hooks are believed to be running at all.
$desired = [ordered]@{
  permissions = [ordered]@{ allow = $allow }
  hooks = [ordered]@{
    PreToolUse = @(
      [ordered]@{ matcher = 'Bash';                 hooks = @([ordered]@{ type='command'; command = "powershell -NoProfile -ExecutionPolicy Bypass -File $hookRoot\hooks\git-guard.ps1";    timeout = 10 }) },
      [ordered]@{ matcher = 'Write|Edit|MultiEdit'; hooks = @([ordered]@{ type='command'; command = "powershell -NoProfile -ExecutionPolicy Bypass -File $hookRoot\hooks\config-guard.ps1"; timeout = 10 }) }
    )
  }
}
foreach ($h in @('git-guard.ps1','config-guard.ps1')) {
  $hp = Join-Path $hookRoot "hooks\$h"
  if (-not (Test-Path $hp)) { throw "Hook missing: $hp. Refusing to write a settings.json that points at a hook which does not exist -- it would fail silently." }
}
$desiredJson = $desired | ConvertTo-Json -Depth 8
$currentJson = if (Test-Path $settingsPath) { Get-Content $settingsPath -Raw } else { '' }
if ($currentJson.Trim() -ne $desiredJson.Trim()) {
  if ($Check) { $issues += "settings.json missing or drifted (hooks would not run)" }
  else { [IO.File]::WriteAllText($settingsPath, $desiredJson, (New-Object Text.UTF8Encoding $false)); Write-Host "  settings.json written: 2 PreToolUse hooks + $($allow.Count) project permission(s)" -ForegroundColor Green }
}

# ---- trust: without it, permissions.allow is SILENTLY IGNORED ---------------
# An isolated config dir has no trust record, so the CLI reports
# "Ignoring N permissions.allow entries ... this workspace has not been trusted"
# and every project permission is discarded. Seed it, keyed on the git common dir.
$dotClaude = Join-Path $cfgDir '.claude.json'
# NOTE: ConvertFrom-Json -AsHashtable is PowerShell 6+. Hooks and bench scripts run
# under Windows PowerShell 5.1, where that parameter does not exist -- and a
# try/catch around it silently yields an empty object, so a seeded value reads back
# as missing. Parse as PSCustomObject and convert by hand.
$dcObj = $null
if (Test-Path $dotClaude) { try { $dcObj = Get-Content $dotClaude -Raw | ConvertFrom-Json } catch { $dcObj = $null } }
$trustKeys = @($cfg.bare, $cfg.trunk) | Where-Object { $_ }
$trusted = @{}
if ($dcObj -and ($dcObj.PSObject.Properties.Name -contains 'projects')) {
  foreach ($pr in $dcObj.projects.PSObject.Properties) {
    if ($pr.Value -and ($pr.Value.PSObject.Properties.Name -contains 'hasTrustDialogAccepted') -and $pr.Value.hasTrustDialogAccepted) {
      $trusted[$pr.Name] = $true
    }
  }
}
$needTrust = @()
foreach ($k in $trustKeys) {
  $norm = $k.Replace([char]92, '/')
  if (-not $trusted.ContainsKey($norm)) { $needTrust += $norm }
}
if ($needTrust.Count -gt 0) {
  if ($Check) { foreach ($n in $needTrust) { $issues += "workspace not trusted for $n (permissions would be ignored)" } }
  else {
    $projects = [ordered]@{}
    foreach ($k in $trusted.Keys) { $projects[$k] = @{ hasTrustDialogAccepted = $true } }
    foreach ($n in $needTrust)    { $projects[$n] = @{ hasTrustDialogAccepted = $true } }
    $outObj = [ordered]@{ projects = $projects }
    [IO.File]::WriteAllText($dotClaude, ($outObj | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding $false))
    Write-Host "  trust seeded for $($needTrust.Count) path(s) -- without this, project permissions are ignored" -ForegroundColor Green
  }
}

if ($Check) {
  if ($issues) { Write-Host "CONFIG NOT READY:" -ForegroundColor Red; $issues | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }; exit 1 }
  Write-Host "Project config ready: $cfgDir" -ForegroundColor Green
  exit 0
}
Write-Host "CLAUDE_CONFIG_DIR = $cfgDir" -ForegroundColor Cyan
