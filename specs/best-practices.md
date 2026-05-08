# Best Practices Reference

Industry-standard best practices for Python, SQL, REST APIs, and software design patterns. This is a reference guide for developers working on the Eclipse OBD-II project.

For project-specific coding conventions, see `specs/standards.md`. For what NOT to do, see `specs/anti-patterns.md`.

**Last Updated**: 2026-02-05

---

## Python Top 20 Best Practices

1. **Use Python 3.13+ and uv for environment management**
2. **Enforce type hints everywhere** (PEP 695 generics)
3. **Use Black + Ruff for formatting and linting**
4. **Adopt Pydantic v2 for data validation**
5. **Prefer async I/O** for network and DB operations
6. **Use httpx instead of requests**
7. **Use FastAPI for modern API development**
8. **Use pytest + coverage for testing**
9. **Adopt TDD for critical modules**
10. **Use Poetry or uv for dependency management**
11. **Use Polars instead of pandas** for large datasets
12. **Use PyTorch or JAX** for ML workloads
13. **Use Typer for CLI tools**
14. **Use Docker for reproducible deployments**
15. **Use MLflow for model tracking**
16. **Use Celery for distributed tasks**
17. **Use Altair or Plotly for visualization**
18. **Use AnyIO for async abstraction**
19. **Use cognitive complexity tools** (complexipy)
20. **Prefer composition over inheritance** in Python OOP

### Project Alignment Notes

| Practice | Our Status |
|----------|-----------|
| Python 3.13+ | Using 3.11+ (per `pyproject.toml`) |
| Black + Ruff | Active (`make lint`, `make format`) |
| pytest + coverage | Active (80% minimum, `make pre-commit`) |
| TDD | Core methodology (`specs/methodology.md`) |
| FastAPI | Companion service on Chi-Srv-01 (`prd-companion-service.md`) |
| Type hints | Enforced via MyPy (`make typecheck`) |
| Async I/O | Planned for companion service (FastAPI) |
| Docker | Not adopted — rsync+SSH deployment to Pi |

---

## SQL Top 20 Design Patterns & Best Practices

1. **Normalize to 3NF** (but avoid over-normalization)
2. **Use lookup tables** for enumerations
3. **Use junction tables** for many-to-many relationships
4. **Use CTEs** for readability
5. **Use window functions** for analytics
6. **Use covering indexes** for frequent queries
7. **Use composite indexes** intentionally
8. **Avoid SELECT \*** in production
9. **Use pagination patterns** (OFFSET/LIMIT or keyset)
10. **Use audit/history tables** for change tracking
11. **Use constraints** (PK, FK, CHECK) aggressively
12. **Use transactions** for multi-step operations
13. **Choose correct isolation levels**
14. **Avoid EAV** unless absolutely necessary
15. **Avoid application-side joins**
16. **Use materialized views** for heavy aggregations
17. **Use partial indexes** for filtered workloads
18. **Use query plans** to diagnose performance
19. **Avoid NULL misuse**
20. **Refactor legacy schemas** incrementally

### Project Alignment Notes

| Practice | Our Status |
|----------|-----------|
| SQLite (Pi) + MariaDB (Chi-Srv-01) | Dual-database architecture |
| WAL mode | Active on Pi SQLite (`specs/architecture.md`) |
| 12 tables, 16 indexes | Defined in architecture |
| Audit/history | sync_log table tracks data sync |
| Transactions | Required per `specs/standards.md` Section 13 |
| Constraints | PK, FK, CHECK, UNIQUE enforced |

---

## REST API Top 20 Best Practices

1. **Use nouns, not verbs**, in resource URIs
2. **Use plural resource names** (/users, /orders)
3. **Use standard HTTP verbs** (GET, POST, PUT, PATCH, DELETE)
4. **Use OpenAPI 3.1** for schema-first design
5. **Version APIs** via URL (/v1/, /v2/)
6. **Use consistent HTTP status codes**
7. **Use JSON** as the default representation
8. **Support pagination, filtering, sorting**
9. **Use idempotent PUT and safe GET**
10. **Use PATCH for partial updates**
11. **Use HATEOAS links** when appropriate
12. **Use correlation IDs** for tracing
13. **Use rate limiting and throttling**
14. **Use API gateways** for cross-cutting concerns
15. **Use consistent error formats**
16. **Use JWT or OAuth2 for auth**
17. **Use resource-based permissions**
18. **Use async operations** for long-running tasks
19. **Document all endpoints** with examples
20. **Treat APIs as contracts** (design-first mindset)

### Project Alignment Notes

| Practice | Our Status |
|----------|-----------|
| FastAPI + OpenAPI | Companion service auto-generates OpenAPI docs |
| API versioning | Planned (/v1/) |
| Auth | API key via `X-API-Key` header, `hmac.compare_digest()` |
| JSON default | Yes |
| Error formats | 5-tier error classification (`src/common/error_handler.py`) |

---

## General Software Design Patterns

1. **Singleton** (use sparingly)
2. **Factory Method**
3. **Abstract Factory**

### Project Usage

| Pattern | Where Used |
|---------|-----------|
| Orchestrator | `src/orchestrator.py` — central lifecycle management |
| Facade | `src/common/` re-export modules (TD-002) |
| Observer | Event-driven status updates |
| Strategy | Tiered PID polling (weighted round-robin) |

---

## Golden Code Patterns

Authoritative source: `specs/golden_code_sample.py`. Apply on every story.

**Structure order within a module.**
Exceptions → Configuration → Utilities → Domain Model → Repository Abstraction → Service Layer → Helpers → CLI → `if __name__ == "__main__"`. Group by responsibility with section comment headers (`# ---- Section Name ---`).

**`from __future__ import annotations`** at the top of every module. Enables deferred evaluation of type hints, avoids forward-reference issues, and allows `list[str]` instead of `List[str]`.

**`@dataclass(slots=True)` and `@dataclass(slots=True, kw_only=True)`**. `slots=True` for memory efficiency and attribute access speed. `kw_only=True` when all fields should be named at construction to prevent positional mistakes.

**`typing.Protocol` for interfaces (not `abc.ABC`).** Structural subtyping — implementations don't need to inherit, they just need to match the shape.

```python
class RecordRepository(Protocol):
    def load(self) -> list[Record]: ...
    def save(self, records: Iterable[Record]) -> None: ...
```

**Dependency injection via constructor.** Services receive dependencies (repositories, config) via `__init__`, not global imports or module-level singletons. Makes testing trivial — pass a mock repository.

```python
@dataclass(slots=True)
class DataService:
    repo: RecordRepository  # injected, not created internally
```

**`@staticmethod` factory methods on dataclasses.** `from_json()`, `from_env_and_args()` for constructing objects from external data, with validation at the boundary.

**Config validation as a method, not a separate validator.** Config objects validate themselves via a `.validate()` method. Raises specific `ConfigError` with clear messages.

**Context managers for cross-cutting concerns.** `@contextlib.contextmanager` for reusable patterns like timing/logging:

```python
@contextlib.contextmanager
def log_duration(activity: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug("Finished %s in %.2f ms", activity, elapsed)
```

**`@lru_cache` for pure, deterministic functions.** Cache results of pure functions (e.g. email normalization) called repeatedly with the same input.

**Deterministic `main()` returning exit code.** `main()` takes optional `argv`, returns `int` exit code, handles all exception tiers at the top level. Entry point is `raise SystemExit(main())`.

**Atomic file writes.** Write to a `.tmp` file first, then `tmp_path.replace(output_path)` for atomic replacement. Prevents corrupted output on crash.

**`__all__` for public API.** Declare `__all__` at module top to explicitly list the public API.

**Exception hierarchy.** Base `AppError` → specific `ConfigError`, `DataError`. Top-level `main()` catches `AppError` (known errors, exit 2), `KeyboardInterrupt` (exit 130), `Exception` (unexpected, exit 1).

**Logging.**
- Module-level `logger = logging.getLogger(__name__)` — never `basicConfig` at import time.
- `configure_logging()` called once in `main()`.
- `logger.info("Loaded %d record(s)", count)` with `%` formatting (not f-strings) for lazy evaluation.
