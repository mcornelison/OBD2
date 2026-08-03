from=Marcus(PM); to=Atlas(Architect); date=2026-08-02; topic=V0.29.24 on-Pi: boot+shutdown splash not rendering + UI froze on bench -- diagnostics handoff (CIO routed this to you); audience=agent; urgency=high; refs=I-042,US-501,US-513,V0.29.24

CIO reports: after deploy+reboot on the bench (NOT car), boot splash did NOT render, shutdown reverse splash did NOT render, and after using the UI the dashboard FROZE. CIO routed it to you (your display lane). I stood down; handing off what I already pulled from Pi `.100` so you don't start cold. Filed I-042 to track; V0.29.24 does NOT get /sprint-validated until this clears.

## Evidence gathered (Pi @ 10.27.27.100, boot 20:19:57 CDT = post-V0.29.24-deploy reboot)

**Units:** splash-boot enabled/inactive; splash-grace static/inactive; splash-grace.path enabled/active; eclipse-states-http active; eclipse-dashboard active; graphical.target active.

**splash-boot ran then exited cleanly:** chromium PID 1735 started 20:20:16, `Deactivated successfully` 20:20:21 (~5s, 2.3s CPU), then `Triggering OnSuccess=`. Unit comment: "Splash exits via JS window.close() at HEALTHY_YIELD / DEGRADED (D-3)." ExecStart loads `http://127.0.0.1:9899/` (kiosk). So a fast boot-to-HEALTHY (US-494 Pi-core-up readiness) would make the boot splash flash briefly then self-close -- may be "didn't see it" rather than "never ran".

**STRONGEST LEAD -- state server route auth (curl on Pi, 127.0.0.1:9899):**
```
GET /            -> 200      GET /boot          -> 401
GET /shutdown.html -> 200    GET /boot.html     -> 401
                             GET /dashboard     -> 401
                             GET /shutdown      -> 401
```
Bare routes `/boot` `/dashboard` `/shutdown` return **401**; only `/` and `*.html` return 200. If the shutdown splash / grace loads `/shutdown` (401) it never renders -- matches the missing shutdown splash. This 401 gate on bare routes looks NEW. **US-501 modified `states_http_server.py` `_injectHtml` (version-chip injection, ~317-323)** this sprint -- prime suspect for a serving-path regression; also check any SSOT-token gate (US-484 lineage) on these routes.

**chromium noise (may be pre-existing, flagging anyway):** dashboard chromium (PID 2015) runs `--js-flags=--no-decommit-pooled-pages` + loads `/dashboard.html`; boot-splash chromium logged repeated dbus `Failed to connect to the bus`, `dconf ... Permission denied` (running uid 0), `unrecognized flag --no-decommit-pooled-pages` on child procs, GCM `PHONE_REGISTRATION_ERROR`.

**Freeze:** happened after interacting with the dashboard on the bench. Dashboard chromium was still process-alive when I checked. US-501/502 touched `carousel.js` + emitters this sprint -- a JS error in the new wiring (version chip / power tile) or a states-http fetch hitting a 401 could hang the render loop. Console/`chrome://` logs will tell.

I'm not touching the Pi further -- it's yours. Ping me with the disposition (regression -> V0.29.25 fast-follow patch, or config/env) and I'll groom whatever story it needs.

-- Marcus
