---
name: pattern-openscad-cli-numeric-part-selector
description: OpenSCAD CLI `-D var="string"` args get mangled across PowerShell → Windows arg parsing — use a numeric variable instead for render selectors
metadata:
  type: pattern
---

When authoring a parametric OpenSCAD source that renders to multiple
STLs from a single file (via a `part` selector), use a **numeric**
selector, not a string selector. Avoids quote-escaping hell at the CLI
boundary.

**Why:** Hit this hard during the display-case v1 render (2026-05-22).
The `.scad` had `part = "assembly"` with `if (part == "back") { ... }`
dispatch. CLI call: `openscad -o out.stl -D 'part="back"' input.scad`.
Across the PowerShell → Windows CreateProcess → OpenSCAD chain, the
inner `"` characters get stripped or reinterpreted. OpenSCAD ended up
trying to set a variable named `back` (no quotes survived), warned
"Ignoring unknown variable 'back'", fell through to the default
`part = "assembly"` branch — which also misrouted, producing
"Current top level object is empty" and exit code 1.

**How to apply:**

```scad
// In the .scad file:
// 0 = assembly visualization, 1 = back, 2 = front, 3 = plunger
part = 0;

if (part == 1) { back_shell(); }
else if (part == 2) { front_shell(); }
else if (part == 3) { plunger(); }
else { assembly_view(); }
```

CLI:
```powershell
& "C:\Program Files\OpenSCAD\openscad.exe" -o stl/back_shell.stl  -D part=1 input.scad
& "C:\Program Files\OpenSCAD\openscad.exe" -o stl/front_shell.stl -D part=2 input.scad
& "C:\Program Files\OpenSCAD\openscad.exe" -o stl/plunger.stl     -D part=3 input.scad
```

No quotes, no escapes, no Windows arg-parsing surprises.

**Bonus pattern** — use `Start-Process` with `-RedirectStandardError`
to capture OpenSCAD's actual error output (which goes to stderr) into
a log file. Then `Read` the log file. Avoids PowerShell's
`NativeCommandError` wrapping that happens with `2>&1` on native exes
(per Windows PowerShell 5.1 quirk documented in system prompt).

```powershell
$p = Start-Process -FilePath "C:\Program Files\OpenSCAD\openscad.exe" `
  -ArgumentList @("-o","out.stl","-D","part=1","input.scad") `
  -RedirectStandardError "render-stderr.log" `
  -RedirectStandardOutput "render-stdout.log" `
  -Wait -NoNewWindow -PassThru
"ExitCode: $($p.ExitCode)"
```

**Where this applies:** Anywhere I'm rendering parametric OpenSCAD from
a CI / batch script on Windows. Less of an issue on macOS/Linux where
shell quoting is more forgiving, but the numeric selector is also more
portable so still preferred.

**OpenSCAD version compatibility note:** This pattern works with
OpenSCAD 2021.01 (which is what's installed on CIO's machine). It
should also work with 2019 and newer; for older versions, the `else if`
chain may need to be a nested `if-else` structure.
