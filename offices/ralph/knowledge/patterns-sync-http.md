# Sync + HTTP Patterns

Load on demand when working on Pi→server sync, HTTP clients, or DNS/network code.

## DNS and Network

**socket.gethostbyaddr() exceptions**
Catch multiple exception types for reverse DNS:
```python
try:
    hostname, aliases, addresses = socket.gethostbyaddr(ip)
    return hostname
except (socket.herror, socket.gaierror, socket.timeout):
    return None
```

**Cache DNS failures**
Cache failed lookups as None to avoid repeated queries for unresolvable IPs:
```python
hostname = resolveHostname(ip)  # Returns None on failure
cache.set(ip, hostname)  # Cache None too
```

---

## Pi HTTP Sync Client (Pi-walk)

**Failed-push invariant — preserve HWM by re-writing with its own value.**
The Pi's `sync_log.last_synced_id` column is the only defense against
unbounded data loss when the server is unreachable: if the Pi advances the
mark past rows that never reached the server and then the Pi SQLite gets
wiped (SD corruption, reinstall, user error), those rows are gone.
Rule: on a successful push, call
`updateHighWaterMark(newMax, batchId, status='ok')`; on an
all-retries-exhausted failure, call
`updateHighWaterMark(currentLastId, batchId, status='failed')` — same id,
so the column is observationally unchanged but the diagnostic trail
(which batch attempted it, when, why) is still written. Tests assert
`lastId == 0` verbatim after a failure with 5 seeded rows. Live in
`src/pi/sync/client.py::SyncClient.pushDelta`.

**HTTP retry classifier — 4xx except 429 fails IMMEDIATELY with zero retries.**
A 401/403 persists across retries (API key is wrong); a 422 persists
(payload is malformed). Retrying just delays failure by
`sum(backoffDelays)` seconds and hammers the server. Correct rule:

```python
def _isRetryableHttpStatus(code: int) -> bool:
    return code == 429 or code >= 500
```

And in the retry loop, `HTTPError` with a non-retryable code breaks out
of the loop on first hit — no backoff sleep, no re-attempt. Tests verify
`len(opener.calls) == 1` for 401/403 and `noSleep.calls == []`.

**Injection seams for retry-with-backoff: httpOpener + sleep.**
Retry clients with real `time.sleep(4.0)` calls turn each failure test
into a 7+ second stall. Inject BOTH `httpOpener=None` (defaults to
`urllib.request.urlopen`) and `sleep=None` (defaults to `time.sleep`) at
construction. Tests pass a `noSleep` fixture that records delay values
into a list without actually sleeping — then assert
`noSleep.calls == [1.0, 2.0, 4.0]` separately from the status-code
assertions. Fast suite stays fast, backoff-schedule drift gets caught.

**urllib.request is enough — don't pull in requests/httpx on the Pi.**
Stdlib `urllib.request.urlopen(Request(url, data=body, headers={...},
method='POST'), timeout=seconds)` covers all network surface the sync
client needs: 2xx via context-manager, 4xx/5xx via `HTTPError` (has
`.code` and `.reason`), DNS/connect fail via `URLError`, deadline via
`TimeoutError`. Zero new supply-chain surface on the Pi.

**urllib Request.header_items() capitalizes header names.**
Urllib normalizes header names when you read them back — `'X-API-Key'`
becomes `'X-api-key'`, `'Content-Type'` becomes `'Content-type'`. Test
assertions on headers need to match the urllib-normalized form or use
`.casefold()` comparisons. Caught in the US-149 payload-shape test.

**Bool-vs-int guard for numeric config fields.**
`isinstance(True, int)` is `True` in Python, so a stray JSON `true`/
`false` in a numeric field silently becomes `1` / `0`. For
`syncTimeoutSeconds=true`, that's a 1-second timeout. Explicit guard in
validators:
```python
if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
    raise ConfigValidationError(...)
```
The bool check MUST come FIRST. Applied in
`src/common/config/validator.py::_validateCompanionService` (US-151).
