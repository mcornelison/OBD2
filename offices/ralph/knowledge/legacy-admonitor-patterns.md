# Legacy adMonitor Patterns (archival)

These patterns were carried over into `agent.md` from the **adMonitor** precursor project (per the 2026-01-21 entry in agent.md's Modification History — *"Added operational tips section with learnings from adMonitor implementation"*). adMonitor was a DNS-based ad-blocker / network monitor. The patterns below have **zero relevance to the Eclipse OBD-II project** — we don't sniff network packets, we don't parse host-file blocklists, and we don't do reverse DNS on IPs.

**Why this file exists**: moved here (not deleted) per CIO Q3 decision 2026-04-20, on the small chance a future story actually touches network-adjacent code. Ralph does NOT need to load this file at startup. Reference only.

**Excised from** `offices/ralph/agent.md` **on** 2026-04-20 (Session 71 closeout, Rex).

---

## scapy / Npcap (network packet sniffer)

**scapy import can fail multiple ways** — catch both ImportError and runtime errors when importing scapy:

```python
try:
    from scapy.all import sniff, get_if_list, IP, TCP, UDP
    SCAPY_AVAILABLE = True
except (ImportError, OSError) as e:
    SCAPY_AVAILABLE = False
```

**Npcap detection** — `get_if_list()` may return an empty list even when scapy imports successfully. Always check for Npcap availability separately:

```python
def isNpcapInstalled() -> bool:
    if not SCAPY_AVAILABLE:
        return False
    try:
        interfaces = get_if_list()
        return len(interfaces) > 0
    except Exception:
        return False
```

Also for reference, the scapy placeholder-names pattern (kept in agent.md under Mocking and Testing, not here) applies to any optional dependency:

```python
try:
    from scapy.all import sniff, get_if_list
except ImportError:
    sniff = None
    get_if_list = None
```

---

## Blocklist / Hosts-File Parsing (ad blocker)

**Hosts format uses multiple prefixes** — both `0.0.0.0` and `127.0.0.1` are valid prefixes in hosts files:

```python
if line.startswith('0.0.0.0 ') or line.startswith('127.0.0.1 '):
    domain = line.split()[1]
```

**EasyList selective parsing** — only parse `||domain.com^` rules from EasyList; ignore `@@`, `/`, and other rule types:

```python
if line.startswith('||') and line.endswith('^'):
    domain = line[2:-1]  # Strip || and ^
```

**Skip localhost entries in hosts files** — filter out `localhost`, `local`, and `localhost.localdomain` from hosts file parsing.

---

## Patterns retained in `agent.md` (kept because Eclipse might touch these)

These adMonitor-origin patterns were **kept in agent.md** because they're general-purpose and could plausibly apply to OBD-II work:

- **DNS / Network** (socket.gethostbyaddr + DNS caching) — could apply to any network diagnostic code (e.g., checking home WiFi before sync). Still in agent.md.
- **VIN Decoding** — directly relevant; Eclipse VIN is in `specs/grounded-knowledge.md`. Still in agent.md.
- **urllib for zero deps** — the Pi HTTP sync client explicitly uses this pattern. Still in agent.md.
- **Configuration patterns** (dot-notation defaults, typed field-list errors) — load-bearing for our 3-layer config system. Still in agent.md.
- **Signal handling** (double Ctrl+C, restore handlers) — still in agent.md, used by orchestrator shutdown.

If you're working on a future Eclipse story that genuinely needs packet capture or hosts-file parsing, this file is the archive. Otherwise ignore.
