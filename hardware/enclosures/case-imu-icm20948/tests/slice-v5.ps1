# Slice the v5 IMU case with the Bambu Studio CLI.
#
# WHY THIS FILE EXISTS: v4's working invocation was recorded only as prose in the spec,
# so v5 had to rediscover it. It is a script now.
#
# ⚠️ Run it from POWERSHELL, not git-bash. MSYS rewrites the ';'-joined --load-settings
# path list into a Windows PATH and the slicer silently produces no file -- that is what
# made v4 Task 6 look like "the CLI is a no-op on this PC". It is not; it was the shell.
#
#   pwsh -File slicer/slice-v5.ps1                 # PLA   (fit-test)
#   pwsh -File slicer/slice-v5.ps1 -Material PETG  # PETG  (keeper)
#
# ⚠️ TWO THINGS THE CLI STILL GETS WRONG -- fix them in the GUI before printing:
#   1. bed plate defaults to Cool Plate 35 C. Select the plate actually installed.
#   2. filament weight reports 0 g (filament_density does not inherit). Gram figures in
#      the spec are computed from length: 1.75 mm PLA ~ 2.98 g/m, PETG ~ 3.07 g/m.
#   3. LID ONLY: enable tree supports, paint support BLOCKERS on the 4 sockets, brim on,
#      variable layer height. Support left in a socket stops the lid seating.

param(
    [ValidateSet('PLA', 'PETG')]
    [string]$Material = 'PLA'
)

$ErrorActionPreference = 'Stop'

$exe = 'C:\Program Files\Bambu Studio\bambu-studio.exe'
$prof = 'C:\Program Files\Bambu Studio\resources\profiles\BBL'
$here = Split-Path -Parent $PSScriptRoot
$out = Join-Path $here 'slicer'

$machine = Join-Path $prof 'machine\Bambu Lab P2S 0.4 nozzle.json'
$process = Join-Path $prof 'process\0.20mm Standard @BBL P2S.json'
$filament = if ($Material -eq 'PETG') {
    Join-Path $prof 'filament\Bambu PETG Basic @BBL P2S 0.4 nozzle.json'
} else {
    Join-Path $prof 'filament\Bambu PLA Basic @BBL P2S.json'
}

foreach ($p in @($exe, $machine, $process, $filament)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "missing: $p" }
}

$suffix = if ($Material -eq 'PETG') { '-petg' } else { '' }

# base: no supports, Arachne walls (the 0.7 mm-class spring fingers are thinner than two
# 0.42 mm lines). lid: rim down, supports added in the GUI -- see the header.
$parts = @(
    @{ stl = 'stl\v5-base.stl';      name = "v5-base$suffix.3mf" },
    @{ stl = 'stl\v5-lid-print.stl'; name = "v5-lid$suffix.3mf" }
)

foreach ($part in $parts) {
    $stl = Join-Path $here $part.stl
    if (-not (Test-Path -LiteralPath $stl)) { throw "missing STL: $stl" }

    $args = @(
        '--load-settings', "$machine;$process",
        '--load-filaments', $filament,
        '--slice', '0',
        '--arrange', '1',
        '--orient', '0',
        '--outputdir', $out,
        '--export-3mf', $part.name,
        $stl
    )

    Write-Host "slicing $($part.name) [$Material] ..."
    $p = Start-Process -FilePath $exe -ArgumentList $args -Wait -NoNewWindow -PassThru
    if ($p.ExitCode -ne 0) { throw "slicer returned $($p.ExitCode) for $($part.name)" }

    $made = Join-Path $out $part.name
    if (-not (Test-Path -LiteralPath $made)) { throw "no file produced: $made" }
    Write-Host ("  OK  {0}  {1:N0} bytes" -f $part.name, (Get-Item -LiteralPath $made).Length)
}

Write-Host ''
Write-Host "done -- $Material. Now open each 3mf in the GUI and fix the bed plate;"
Write-Host 'for the lid also add tree supports + socket blockers + brim.'
