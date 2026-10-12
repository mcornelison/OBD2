<#
.SYNOPSIS
  Resolve a project's role roster. Dot-source this; do not run it directly.

.DESCRIPTION
  THE ROSTER IS NEVER HARDCODED. A hardcoded list is not wrong when it is written --
  it is a correct list, frozen, and it becomes wrong the moment it is copied to the
  next project. That is a nastier failure than a typo, because there is nothing to
  notice at the time.

  Three axes, deliberately independent (see docs\CONVENTIONS.md):

    slug       the office directory. The addressable key. PERMANENT -- git branches,
               paths and years of history hang off it. Never renamed.
    archetype  the generic function: pm | architect | developer | sme | qa | ui.
               The only axis stable ACROSS projects. Generic tooling keys off THIS.
    persona    the agent's name. For humans and inter-agent messages. NEVER a key --
               persona names collide across projects (one fleet has "Atlas" as an
               architect in one project and a project manager in another).
    mode       interactive | headless. Orthogonal to archetype, and the axis with
               runtime teeth: a headless agent cannot answer a prompt or read a
               remedy line, so anything that blocks it must be loud, parseable and
               non-destructive.

  Resolution order, most authoritative first:
    1. fleet.json "roles" as records   (V2 schema -- preferred)
    2. fleet.json "roles" as strings   (legacy; archetype/persona/mode inferred)
    3. structural discovery from disk  (no roles key at all)

  Structural discovery does not use a name list. A role is a directory that has a
  charter AND its own .claude\commands\. Everything else under offices\ -- shared
  libraries, knowledge stores, stray inboxes -- is not a role. Scored 14/14 across
  two real projects with six and four roles respectively.
#>

Set-StrictMode -Version Latest

# Archetype hints. These are a CONVENIENCE for legacy projects that declare only
# names. They are guesses, and Get-FleetRoles says so. A V2 project declares the
# archetype explicitly and never relies on this table.
$script:ArchetypeHints = @{
  'pm' = 'pm'; 'projectmanager' = 'pm'; 'project-manager' = 'pm'
  'architect' = 'architect'; 'arch' = 'architect'
  'ralph' = 'developer'; 'dev' = 'developer'; 'developer' = 'developer'
  'tester' = 'qa'; 'qa' = 'qa'; 'test' = 'qa'
  'uideveloper' = 'ui'; 'ui' = 'ui'; 'uidesigner' = 'ui'; 'uidev' = 'ui'
}

function Get-FleetArchetypeHint {
  param([string]$Slug)
  $k = $Slug.ToLower()
  if ($script:ArchetypeHints.ContainsKey($k)) { return $script:ArchetypeHints[$k] }
  return 'unknown'
}

function Get-FleetPersonaFromCharter {
  param([string]$OfficeDir)
  # Best-effort only. Charters are prose; this is for reporting, never for keying.
  # CLAUDE.md/agent.md carry the identity; CHARTER.md is a mandate doc whose
  # heading starts with the word CHARTER, so it is tried last and matched specially.
  foreach ($n in @('CLAUDE.md','claude.md','agent.md','CHARTER.md')) {
    $p = Join-Path $OfficeDir $n
    if (Test-Path $p) {
      $m = Select-String -Path $p -Pattern 'You are \*\*([^*]+)\*\*' -EA SilentlyContinue | Select-Object -First 1
      if ($m) { return ($m.Matches[0].Groups[1].Value -replace '\(.*$','').Trim() }
      # charters that lead with a heading instead: "# Dr. Pixel - Office CLAUDE.md"
      $c = Select-String -Path $p -Pattern '^#\s+CHARTER\s+[-—]\s+([^-—]+)' -EA SilentlyContinue | Select-Object -First 1
      if ($c) { return ($c.Matches[0].Groups[1].Value -replace '\(.*$','').Trim() }
      $h = Select-String -Path $p -Pattern '^#\s+([A-Z][A-Za-z.\- ]{1,30}?)\s+[-—]' -EA SilentlyContinue | Select-Object -First 1
      if ($h -and $h.Matches[0].Groups[1].Value.Trim() -notmatch '^(CHARTER|README|AGENT|CLAUDE)$|\.(md|txt|ps1|py|json)$') {
        return $h.Matches[0].Groups[1].Value.Trim()
      }
    }
  }
  return ''
}

function Test-FleetIsRole {
  param([string]$OfficeDir)
  # A role has a charter AND its own commands. Structure, not a name list.
  $hasCharter = @('CHARTER.md','CLAUDE.md','claude.md','agent.md') |
                Where-Object { Test-Path (Join-Path $OfficeDir $_) } | Select-Object -First 1
  $cmdDir = Join-Path $OfficeDir '.claude\commands'
  $hasCmds = (Test-Path $cmdDir) -and @(Get-ChildItem $cmdDir -Filter *.md -EA SilentlyContinue).Count -gt 0
  return [bool]$hasCharter -and $hasCmds
}

function Get-FleetRoles {
  <#
    Returns normalised records: slug, archetype, persona, mode, source.
    -Warn emits a warning for every value that was inferred rather than declared.
  #>
  param(
    [Parameter(Mandatory)]$Cfg,
    [string]$OfficesRoot,
    [switch]$Warn
  )

  if (-not $OfficesRoot) { $OfficesRoot = Join-Path $Cfg.share 'offices' }
  $out = @()

  $declared = $null
  if ($Cfg.PSObject.Properties.Name -contains 'roles') { $declared = @($Cfg.roles) }

  if ($declared -and $declared.Count -gt 0) {
    foreach ($r in $declared) {
      if ($r -is [string]) {
        $slug = $r
        $arch = Get-FleetArchetypeHint $slug
        $office = Join-Path $OfficesRoot $slug
        $persona = if (Test-Path $office) { Get-FleetPersonaFromCharter $office } else { '' }
        if ($Warn) {
          Write-Warning "roles['$slug'] is a bare string. archetype inferred as '$arch'; mode assumed 'interactive'. Declare it as a record to be explicit."
        }
        $out += [pscustomobject]@{ slug=$slug; archetype=$arch; persona=$persona; mode='interactive'; source='legacy-string' }
      } else {
        $slug = $r.slug
        $arch = if ($r.PSObject.Properties.Name -contains 'archetype' -and $r.archetype) { $r.archetype } else { Get-FleetArchetypeHint $slug }
        $per  = if ($r.PSObject.Properties.Name -contains 'persona')   { $r.persona } else { '' }
        $mode = if ($r.PSObject.Properties.Name -contains 'mode' -and $r.mode) { $r.mode } else { 'interactive' }
        $out += [pscustomobject]@{ slug=$slug; archetype=$arch; persona=$per; mode=$mode; source='fleet.json' }
      }
    }
    return $out
  }

  # 3. no roles key -- discover structurally
  if (-not (Test-Path $OfficesRoot)) {
    throw "No 'roles' in fleet.json and no offices dir at $OfficesRoot. Cannot resolve the roster."
  }
  foreach ($d in Get-ChildItem $OfficesRoot -Directory -EA SilentlyContinue | Sort-Object Name) {
    if ($d.Name.StartsWith('_') -or $d.Name.StartsWith('.')) { continue }
    if (-not (Test-FleetIsRole $d.FullName)) { continue }
    $arch = Get-FleetArchetypeHint $d.Name
    if ($Warn -and $arch -eq 'unknown') {
      Write-Warning "Discovered role '$($d.Name)' but could not infer its archetype. Declare it in fleet.json so generic tooling can key off it."
    }
    $out += [pscustomobject]@{
      slug=$d.Name; archetype=$arch; persona=(Get-FleetPersonaFromCharter $d.FullName)
      mode='interactive'; source='discovered'
    }
  }
  if (-not $out) { throw "No roles found under $OfficesRoot. A role needs a charter and its own .claude\commands\." }
  return $out
}

function Get-FleetFileHash {
  <#
    MD5 of a file, without Get-FileHash.

    Get-FileHash is NOT always available under Windows PowerShell 5.1: if
    PSModulePath includes a PowerShell 7 Modules directory, 5.1 loads PS7's
    Microsoft.PowerShell.Utility and the cmdlet does not resolve --
    "The term 'Get-FileHash' is not recognized". That is an environment
    condition nobody sets deliberately, and it broke bench leasing on a machine
    where everything else worked. .NET is always there.
  #>
  param([Parameter(Mandatory)][string]$Path)
  $md5 = [Security.Cryptography.MD5]::Create()
  try {
    $fs = [IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($md5.ComputeHash($fs)) -replace '-','') }
    finally { $fs.Dispose() }
  } finally { $md5.Dispose() }
}
