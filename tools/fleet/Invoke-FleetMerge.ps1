<#
.SYNOPSIS
  The only thing allowed to write the trunk. Serializes merges behind an exclusive
  lock, enforces the ticket's declared file surface, runs the gate, then merges.

.DESCRIPTION
  Run this from the integrator office (or a scheduled sweep). It drains board\review\
  one ticket at a time. Because every worktree shares one object store, the merge is
  purely local — no fetch, no push, no transport, nothing to race on.

.NOTES
  Invoke with -ProjectRoot <path to the project root holding fleet.json>, and
  -Gate <command that must exit 0> to run the test gate before each merge.
  -Push also pushes the trunk branch to origin. Defaults target this fleet.
#>
[CmdletBinding()]
param(
  # The project root, directly. The old -Client/-Project/-LocalRoot trio built
  # <LocalRoot>\<Client>\<Project>, which for this fleet resolved to
  # C:\agents\OBD2\OBD2v3 -- a path that does not exist. The layout is flat.
  [string]$ProjectRoot = 'C:\agents\OBD2v3',
  [string]$Gate,                       # e.g. "npm test" — must exit 0
  [int]$LockTimeoutSec = 900,
  [switch]$Push
)

$ErrorActionPreference = 'Stop'
$localDir = $ProjectRoot
if (-not (Test-Path (Join-Path $localDir 'fleet.json'))) {
  throw "No fleet.json at $localDir -- pass -ProjectRoot pointing at the project root."
}
$cfg      = Get-Content (Join-Path $localDir 'fleet.json') -Raw | ConvertFrom-Json
$lockPath = Join-Path $localDir '.merge.lock'

function Enter-MergeLock {
  $deadline = (Get-Date).AddSeconds($LockTimeoutSec)
  while ($true) {
    try {
      # CreateNew + FileShare.None is atomic on NTFS. Held open for the whole merge.
      return [System.IO.File]::Open($lockPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None)
    } catch [System.IO.IOException] {
      if ((Get-Date) -gt $deadline) { throw "Merge lock held too long: $lockPath" }
      Write-Host "  waiting for merge lock..." -ForegroundColor DarkGray
      Start-Sleep -Seconds 5
    }
  }
}

function Test-Surface($path, $globs) {
  foreach ($g in $globs) {
    $rx = '^' + ([regex]::Escape($g) -replace '\\\*\\\*', '.*' -replace '\\\*', '[^/]*') + '$'
    if ($path -match $rx) { return $true }
  }
  return $false
}

$reviewDir = Join-Path $cfg.share 'board\review'
$doneDir   = Join-Path $cfg.share 'board\done'
$tickets   = @(Get-ChildItem -Path $reviewDir -Filter *.md -ErrorAction SilentlyContinue | Sort-Object Name)

if (-not $tickets) { Write-Host "Nothing in review." ; exit 0 }

$lock = Enter-MergeLock
try {
  foreach ($t in $tickets) {
    # Lease metadata comes from the BENCH'S OWN lease.json, not from the ticket
    # markdown. New-Bench.ps1 writes lease.json; nothing writes branch/surface
    # into the ticket. Parsing it out of prose meant two sources for one fact --
    # and the one being parsed did not exist, so every ticket was skipped with
    # "no branch declared". The lease is machine-written and authoritative.
    $ticket = $t.BaseName
    $lease  = Get-ChildItem (Join-Path $cfg.worktrees '*') -Directory -ErrorAction SilentlyContinue |
              ForEach-Object { Join-Path $_.FullName '.fleet\lease.json' } |
              Where-Object { Test-Path $_ } |
              ForEach-Object {
                $j = Get-Content $_ -Raw | ConvertFrom-Json
                if ($j.ticket -eq $ticket) { [pscustomobject]@{ json = $j; dir = (Split-Path (Split-Path $_ -Parent) -Parent) } }
              } | Select-Object -First 1
    if (-not $lease) {
      Write-Warning "$($t.Name): no leased bench found for ticket $ticket (looked for .fleet\lease.json under $($cfg.worktrees)). Skipping."
      continue
    }
    $branch  = $lease.json.branch
    $wt      = $lease.dir
    $surface = @($lease.json.surface)
    if (-not $branch)  { Write-Warning "$($t.Name): lease has no branch, skipping"; continue }
    if (-not $surface) { $surface = @('**') }

    Write-Host "`n=== $($t.BaseName)  [$branch]" -ForegroundColor Cyan

    Push-Location $cfg.trunk
    try {
      # 1. surface check — reject edits the ticket never claimed
      $changed = git diff --name-only "$($cfg.trunkBranch)...$branch"
      $outside = @($changed | Where-Object { -not (Test-Surface $_ $surface) })
      if ($outside) {
        Write-Warning "REJECTED — edits outside declared surface:`n  $($outside -join "`n  ")"
        Add-Content $t.FullName "`n## REJECTED $(Get-Date -f s)`nOutside surface:`n$($outside | ForEach-Object { "- $_" } | Out-String)"
        Move-Item $t.FullName (Join-Path $cfg.share 'board\wip') -Force
        continue
      }

      # 2. merge (no-ff so every ticket is one revertible bubble)
      git merge --no-ff --no-edit -m "$($t.BaseName): merge $branch" $branch
      if ($LASTEXITCODE -ne 0) {
        git merge --abort
        Write-Warning "REJECTED — conflicts with trunk. Agent must merge trunk into its branch first."
        Move-Item $t.FullName (Join-Path $cfg.share 'board\wip') -Force
        continue
      }

      # 3. gate
      if ($Gate) {
        Write-Host "  gate: $Gate" -ForegroundColor DarkGray
        cmd /c $Gate
        if ($LASTEXITCODE -ne 0) {
          git reset --hard HEAD~1     # safe: trunk worktree, integrator-only, under lock
          Write-Warning "REJECTED — gate failed, trunk rolled back."
          Move-Item $t.FullName (Join-Path $cfg.share 'board\wip') -Force
          continue
        }
      }

      if ($Push) { git push origin $($cfg.trunkBranch) }

      # 4. release the worktree and the branch
      # On Windows a bench whose agent is still running holds an open handle on
      # its own directory, and `worktree remove` fails with a lock error that
      # reads like corruption. Probe first and say what is actually wrong -- the
      # operator needs "the agent must exit", not a retry prompt. (The Step 6
      # guard-test bench hit exactly this.)
      if ($wt -and (Test-Path $wt)) {
        $locked = $false
        try {
          $probe = Join-Path $wt ('.merge-lock-probe-' + [guid]::NewGuid().ToString('N'))
          New-Item -ItemType File -Path $probe -ErrorAction Stop | Out-Null
          Remove-Item $probe -Force -ErrorAction Stop
          [IO.Directory]::GetFiles($wt) | Out-Null
        } catch { $locked = $true }
        if (-not $locked) {
          try { [IO.Directory]::Move($wt, "$wt.lockcheck"); [IO.Directory]::Move("$wt.lockcheck", $wt) }
          catch { $locked = $true }
        }
        if ($locked) {
          Write-Warning "Bench still in use -- the agent must exit first: $wt"
          Write-Warning "  The merge SUCCEEDED; only the worktree reclaim is deferred."
          Write-Warning "  Close that Claude Code session, then: git --git-dir=$($cfg.bare) worktree prune"
        } else {
          git --git-dir=$($cfg.bare) worktree remove --force $wt
        }
      }
      # `branch -d` in a BARE repo evaluates "fully merged" against THAT repo's
      # HEAD, not against the trunk branch. This store's HEAD was refs/heads/master
      # -- a branch it does not even have -- so -d refused every merged branch, and
      # `2>$null` swallowed the refusal. Branches accumulated silently. Check
      # ancestry against the trunk branch explicitly, and be loud on failure.
      git --git-dir=$($cfg.bare) merge-base --is-ancestor $branch $($cfg.trunkBranch)
      if ($LASTEXITCODE -eq 0) {
        git --git-dir=$($cfg.bare) branch -D $branch
        if ($LASTEXITCODE -ne 0) { Write-Warning "Branch delete FAILED: $branch" }
      } else {
        Write-Warning "Branch NOT deleted -- $branch is not an ancestor of $($cfg.trunkBranch) after a successful merge. Investigate before reusing the name."
      }

      New-Item -ItemType Directory -Path $doneDir -Force | Out-Null
      Add-Content $t.FullName "`n## MERGED $(Get-Date -f s) -> $($cfg.trunkBranch)"
      Move-Item $t.FullName $doneDir -Force
      Write-Host "  MERGED" -ForegroundColor Green
    }
    finally { Pop-Location }
  }
}
finally {
  $lock.Close(); $lock.Dispose()
  Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}
