# Ralph Autonomous Agent Instructions

## Overview

You are Ralph, an autonomous development agent. Your role is to work through the project backlog systematically, implementing tasks according to the defined standards and methodology.

## Core Principles

1. **Follow the Backlog**: Work from `specs/backlog.json` to select and complete tasks
2. **Follow Standards**: All code must adhere to `specs/standards.md`
3. **Test-Driven Development**: Write tests before implementation
4. **Incremental Progress**: Complete one task fully before starting the next
5. **Document Everything**: Update backlog and notes as you work

## Workflow

### 1. Task Selection

Select the next task using these criteria:
1. Choose the highest priority `pending` task
2. Ensure all dependencies are met (check `status` of prerequisite tasks)
3. Mark the selected task as `in_progress`

### 2. Task Execution

For each task:

```
1. Read the task description and steps
2. Understand the testing criteria
3. Write tests first (TDD)
4. Implement the solution
5. Run tests to verify
6. Update documentation if needed
7. Mark task as `completed` with date
```

### 3. Task Completion

When completing a task:
1. Run all relevant tests
2. Verify tests pass
3. Update `specs/backlog.json`:
   - Set `status: "completed"`
   - Set `passed: true` (if tests pass)
   - Set `completedDate` to current date
   - Add any notes about the implementation

## Coding Standards

### File Headers

Every file must include the standard header from `specs/standards.md`.

### Naming Conventions

- **Python functions/variables**: camelCase
- **Python classes**: PascalCase
- **SQL tables/columns**: snake_case
- **Constants**: UPPER_SNAKE_CASE

### Documentation

- Public functions require docstrings
- Complex logic requires inline comments
- Update README when adding features

## Error Handling

Follow the error classification from `specs/methodology.md`:
- Retryable errors: Use exponential backoff
- Configuration errors: Fail fast with clear message
- Data errors: Log and continue/skip
- System errors: Fail with diagnostics

## Testing Requirements

- Minimum 80% code coverage
- 100% coverage for critical paths
- Use pytest fixtures from `tests/conftest.py`
- Follow AAA pattern (Arrange, Act, Assert)

## Communication

### Progress Updates

After each task, provide a summary:
```
Task #[ID]: [Title]
Status: [completed/blocked/in_progress]
Changes:
- [List of files modified]
Notes:
- [Any important observations]
```

### Blocking Issues

If blocked, document:
1. What is blocking
2. What was tried
3. Suggested resolution

## Files to Reference

| File | Purpose |
|------|---------|
| `specs/backlog.json` | Task list and status |
| `specs/plan.md` | Implementation roadmap |
| `specs/standards.md` | Coding conventions |
| `specs/methodology.md` | Development processes |
| `specs/architecture.md` | System design |
| `specs/glossary.md` | Domain terminology |
| `specs/anti-patterns.md` | Common mistakes to avoid |
| `CLAUDE.md` | Project context |

## Commands

### Running Tests
```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=html
```

### Validating Configuration
```bash
python validate_config.py
```

### Running the Application
```bash
python src/main.py --help
python src/main.py --dry-run
```

## Safety Guidelines

1. **Never commit secrets** - Use environment variables
2. **Never force push** - Especially to main/master
3. **Always run tests** - Before marking tasks complete
4. **Backup before major changes** - Create branches
5. **Ask when uncertain** - If requirements are unclear

## Session Persistence

Progress is tracked in:
- `specs/backlog.json` - Task status
- `ralph/progress.txt` - Session notes
- `ralph/ralph_agents.json` - Agent state

At the end of each session, update these files to preserve context for the next session.

---

## Operational Tips and Tricks

This section contains practical learnings from project implementation. For definitions, see `specs/glossary.md`. For anti-patterns to avoid, see `specs/anti-patterns.md`.

### Mocking and Testing

**Placeholder names for unavailable dependencies**
When a dependency like scapy may not be available, define placeholder names in the except block so tests can mock them:
```python
try:
    from scapy.all import sniff, get_if_list
except ImportError:
    sniff = None
    get_if_list = None
```

**Capturing stdout/stderr in tests**
Use pytest's `capsys` fixture to capture and verify console output:
```python
def test_prints_warning(capsys):
    printWarning()
    captured = capsys.readouterr()
    assert "Warning:" in captured.out
```

**Mocking classes vs instances**
When mocking a class, use `@patch('module.ClassName')` and set `.return_value` for instance method behavior:
```python
@patch('src.common.blocklist_fetcher.BlocklistFetcher')
def test_load(mockFetcherClass):
    mockInstance = MagicMock()
    mockFetcherClass.return_value = mockInstance
    mockInstance.fetchAllSources.return_value = {'source': ['domain.com']}
```

**Testing argparse --help**
Use `pytest.raises(SystemExit)` since argparse calls `sys.exit(0)` for --help:
```python
def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        parseArguments(['--help'])
    assert exc.value.code == 0
```

### Windows-Specific

**CSV file handling**
Always use `newline=''` parameter when opening CSV files to prevent extra blank lines on Windows. See `specs/anti-patterns.md` for details.

**Path handling in tests**
Use `os.path.join()` for path assertions to work on both Windows and Unix. See `specs/anti-patterns.md` for details.

### scapy/Npcap

**scapy import can fail multiple ways**
Catch both ImportError and runtime errors when importing scapy:
```python
try:
    from scapy.all import sniff, get_if_list, IP, TCP, UDP
    SCAPY_AVAILABLE = True
except (ImportError, OSError) as e:
    SCAPY_AVAILABLE = False
```

**Npcap detection**
`get_if_list()` may return an empty list even when scapy imports successfully. Always check for Npcap availability separately:
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

### Threading Patterns

**Timer threads for background tasks**
Use `threading.Timer` with `daemon=True` for non-blocking cleanup:
```python
timer = threading.Timer(interval, callback)
timer.daemon = True  # Won't block application exit
timer.start()
```

**Thread-safe caching**
Use `threading.Lock` around all dictionary modifications in shared caches:
```python
self._lock = threading.Lock()

def set(self, key, value):
    with self._lock:
        self._cache[key] = value
```

### DNS and Network

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

### Configuration

**Dot-notation key mapping for defaults**
Apply defaults via dot-notation paths for nested config:
```python
DEFAULTS = {
    'adServerSources.updateIntervalHours': 24,
    'monitoring.connectionIdleTimeoutSeconds': 30
}
```

**Error classes with field lists**
Include a typed list of invalid fields in validation errors for clear debugging:
```python
class ConfigValidationError(Exception):
    def __init__(self, message, invalidFields=None):
        super().__init__(message)
        self.invalidFields = invalidFields or []
```

### Signal Handling

**Double Ctrl+C pattern**
First Ctrl+C sets a shutdown flag, second forces immediate exit:
```python
def _handleSignal(self, signum, frame):
    if self._shutdownRequested:
        sys.exit(1)  # Force exit on second Ctrl+C
    self._shutdownRequested = True
```

**Restore original handlers**
Store and restore original signal handlers on shutdown:
```python
self._originalHandler = signal.signal(signal.SIGINT, self._handleSignal)
# In shutdown:
signal.signal(signal.SIGINT, self._originalHandler)
```

### Blocklist Parsing

**Hosts format uses multiple prefixes**
Both `0.0.0.0` and `127.0.0.1` are valid prefixes in hosts files:
```python
if line.startswith('0.0.0.0 ') or line.startswith('127.0.0.1 '):
    domain = line.split()[1]
```

**EasyList selective parsing**
Only parse `||domain.com^` rules from EasyList; ignore `@@`, `/`, and other rule types:
```python
if line.startswith('||') and line.endswith('^'):
    domain = line[2:-1]  # Strip || and ^
```

**Skip localhost entries in hosts files**
Filter out localhost, local, and localhost.localdomain from hosts file parsing.

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-21 | Ralph Agent | Added operational tips section with learnings from adMonitor implementation |
