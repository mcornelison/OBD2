# Re-render warning-480x320.png from warning.svg (UIDEV-014, Iris).
# Chromium draws it, the same engine as the kiosk, so the PNG matches what the
# splash page would draw. Run from anywhere: .\render.ps1
# Check after: 480x320, RGB, every corner pixel = #0A0A0A.
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$here = $PSScriptRoot
$svg = (Join-Path $here "warning.svg").Replace([char]92, [char]47)
$png = Join-Path $here "warning-480x320.png"
# Start-Process -Wait: chrome.exe is a GUI binary, so a bare call returns
# before the screenshot is written.
Start-Process -FilePath $chrome -Wait -ArgumentList @(
  "--headless=new", "--disable-gpu", "--hide-scrollbars",
  "--force-device-scale-factor=1", "--window-size=480,320",
  "--default-background-color=0A0A0AFF",
  "--screenshot=`"$png`"", "file:///$svg")
