
#!/usr/bin/env python3
"""Golden Python module example (single-file best-practices).

This module demonstrates modern Python best practices in a single .py file:

- Type hints throughout (PEP 484/526) and `from __future__ import annotations`.
- Clear module- and function-level docstrings (PEP 257) using Google style.
- `dataclasses` for simple data models and `typing.Protocol` for interfaces.
- Cohesive structure: configuration -> domain model -> repository -> service -> CLI.
- Robust error handling with custom exceptions and clean exit codes.
- Standard logging configured via one function; no prints in library code.
- Path handling via `pathlib.Path` and context managers for I/O.
- Pure, testable, side-effect-free helpers (with doctests where helpful).
- Dependency injection (service receives repository interface) for testability.
- Deterministic main entrypoint (`main()`) returning an exit code.

Run it as a script:
    $ python golden_code_sample.py --input data.json --output out.json --log-level INFO

The file format expected for `--input` is either a JSON array of objects or
newline-delimited JSON (one JSON object per line). The output is a compact JSON
array.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Protocol
from pathlib import Path
import argparse
import contextlib
import json
import logging
import os
import sys
from functools import lru_cache

__all__ = [
    "Config",
    "Record",
    "RecordRepository",
    "FileRepository",
    "DataService",
    "main",
]

# Create a module-level logger; libraries should not call basicConfig at import time.
logger = logging.getLogger(__name__)

# ---- Exceptions -----------------------------------------------------------------

class AppError(Exception):
    """Base error for the application."""


class ConfigError(AppError):
    """Raised when configuration is invalid or incomplete."""


class DataError(AppError):
    """Raised when input data is invalid or cannot be processed."""


# ---- Configuration ---------------------------------------------------------------

@dataclass(slots=True)
class Config:
    """Runtime configuration for the application.

    Attributes:
        input_path: Path to input JSON or JSON Lines file.
        output_path: Path to write the transformed JSON array.
        log_level: Logging level name (e.g., "INFO", "DEBUG").
    """

    input_path: Path
    output_path: Path
    log_level: str = "INFO"

    def validate(self) -> None:
        """Validate the configuration.

        Raises:
            ConfigError: If validation fails.
        """
        if not self.input_path:
            raise ConfigError("--input is required")
        if not self.input_path.exists():
            raise ConfigError(f"Input does not exist: {self.input_path}")
        if self.input_path.is_dir():
            raise ConfigError(f"Input must be a file, got directory: {self.input_path}")
        if not self.output_path:
            raise ConfigError("--output is required")
        if self.output_path.exists() and self.output_path.is_dir():
            raise ConfigError(f"Output cannot be a directory: {self.output_path}")
        try:
            logging._nameToLevel[self.log_level.upper()]
        except KeyError as exc:
            raise ConfigError(f"Invalid log level: {self.log_level}") from exc

    @staticmethod
    def from_env_and_args(ns: argparse.Namespace) -> "Config":
        """Build configuration from CLI args with environment fallbacks.

        Environment variables:
            APP_LOG_LEVEL: Overrides the logging level.

        Args:
            ns: Parsed argparse namespace.
        """
        log_level = (ns.log_level or os.getenv("APP_LOG_LEVEL") or "INFO").upper()
        return Config(input_path=ns.input, output_path=ns.output, log_level=log_level)


def configure_logging(level_name: str = "INFO") -> None:
    """Configure root logging for the application.

    This should be called once in `main()`. Library modules should rely on
    module-level loggers and never configure logging at import time.
    """
    level = logging.getLevelName(level_name.upper())
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---- Utilities ------------------------------------------------------------------

@contextlib.contextmanager
def log_duration(activity: str) -> Iterator[None]:
    """Context manager to log the duration of an activity.

    Example:
        >>> import time
        >>> with log_duration("sleeping"):
        ...     _ = 1  # lightweight doctest (no actual sleep)
    """
    import time

    start = time.perf_counter()
    logger.debug("Starting %s", activity)
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug("Finished %s in %.2f ms", activity, elapsed)


@lru_cache(maxsize=256)
def normalize_email(value: str) -> str:
    """Normalize an email address deterministically.

    Operations:
      * Strips whitespace
      * Lowercases the address
      * Normalizes common provider aliases (example only)

    Args:
        value: Raw email string.

    Returns:
        Normalized email string.

    >>> normalize_email("  USER+tag@Example.COM  ")
    'user+tag@example.com'
    """
    value = value.strip().lower()
    # Example normalization: canonicalize common domains if needed.
    value = value.replace("gmail.com", "gmail.com")  # placeholder for extensibility
    return value


# ---- Domain Model ----------------------------------------------------------------

@dataclass(slots=True, kw_only=True)
class Record:
    """Represents a single person record.

    Attributes:
        id: Unique integer identifier.
        name: Full name.
        email: Email address.
    """

    id: int
    name: str
    email: str

    def normalized(self) -> "Record":
        """Return a *new* Record with normalized fields.

        >>> r = Record(id=1, name="  Ada LOVELACE  ", email=" ADA@EXAMPLE.COM ")
        >>> r2 = r.normalized()
        >>> (r2.name, r2.email)
        ('Ada Lovelace', 'ada@example.com')
        """
        return Record(
            id=self.id,
            name=_titlecase_name(self.name),
            email=normalize_email(self.email),
        )

    @staticmethod
    def from_json(obj: dict[str, Any]) -> "Record":
        """Create a Record from raw JSON with validation.

        Raises:
            DataError: If required fields are missing or invalid types.
        """
        try:
            id_ = int(obj["id"])  # may raise KeyError or ValueError
            name = str(obj["name"]).strip()
            email = str(obj["email"]).strip()
        except (KeyError, ValueError, TypeError) as exc:
            raise DataError(f"Invalid record payload: {obj!r}") from exc
        if not name:
            raise DataError("Record 'name' cannot be empty")
        if "@" not in email:
            raise DataError("Record 'email' must contain '@'")
        return Record(id=id_, name=name, email=email)


# ---- Repository Abstraction ------------------------------------------------------

class RecordRepository(Protocol):
    """Interface for loading and saving records."""

    def load(self) -> list[Record]:
        """Load records from a data source."""

    def save(self, records: Iterable[Record]) -> None:
        """Persist records to a data sink."""


@dataclass(slots=True)
class FileRepository:
    """File-based repository implementing `RecordRepository`.

    Supports reading either a JSON array of objects or newline-delimited JSON
    (JSON Lines). Writes a compact JSON array.
    """

    input_path: Path
    output_path: Path

    def load(self) -> list[Record]:
        with log_duration(f"load:{self.input_path}"):
            with self.input_path.open("r", encoding="utf-8") as f:
                head = f.read(1)
                f.seek(0)
                if head == "[":
                    raw = json.load(f)
                    if not isinstance(raw, list):
                        raise DataError("Expected a JSON array at top level")
                    items = raw
                else:
                    items = [json.loads(line) for line in f if line.strip()]
        records: list[Record] = [Record.from_json(obj) for obj in items]
        logger.info("Loaded %d record(s)", len(records))
        return records

    def save(self, records: Iterable[Record]) -> None:
        with log_duration(f"save:{self.output_path}"):
            data = [dataclasses_asdict(r) for r in records]
            tmp_path = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            tmp_path.replace(self.output_path)
        logger.info("Wrote %s", self.output_path)


# ---- Service Layer ---------------------------------------------------------------

@dataclass(slots=True)
class DataService:
    """Business logic operating on `Record` entities."""

    repo: RecordRepository

    def process(self) -> int:
        """Load, transform, de-duplicate by email, and save records.

        Returns:
            The number of unique records written.
        """
        records = self.repo.load()
        # Normalize
        records = [r.normalized() for r in records]
        # Deduplicate by email, keep first occurrence (stable)
        seen: set[str] = set()
        unique: list[Record] = []
        for r in records:
            if r.email not in seen:
                seen.add(r.email)
                unique.append(r)
        self.repo.save(unique)
        return len(unique)


# ---- Helpers --------------------------------------------------------------------

def dataclasses_asdict(obj: Any) -> Any:
    """Convert dataclass instances into plain Python objects recursively.

    This avoids importing `dataclasses.asdict`, which can be slow for large
    trees and may copy more than necessary; for a shallow structure like ours,
    either is fine. This version keeps control explicit.
    """
    if hasattr(obj, "__dataclass_fields__"):
        return {k: dataclasses_asdict(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, (list, tuple)):
        return [dataclasses_asdict(i) for i in obj]
    return obj


def _titlecase_name(value: str) -> str:
    """Title-case a human name conservatively.

    Preserves common particles (e.g., "van", "de") and handles extra
    whitespace.

    >>> _titlecase_name("  aDA   lovelace  ")
    'Ada Lovelace'
    >>> _titlecase_name("grace VAN rossum")
    'Grace Van Rossum'
    """
    particles = {"van", "von", "de", "da", "del", "di"}
    parts = [p for p in value.strip().split() if p]
    titled: list[str] = []
    for i, p in enumerate(parts):
        low = p.lower()
        if i > 0 and low in particles:
            titled.append(low)
        else:
            titled.append(low.capitalize())
    return " ".join(titled)


# ---- CLI ------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=Path(__file__).name,
        description=(
            "Load records from JSON/JSONL, normalize and de-duplicate by email, "
            "then write a compact JSON array."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to input .json or .jsonl file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to output .json file",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.getenv("APP_LOG_LEVEL", "INFO"),
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level (env: APP_LOG_LEVEL)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Program entrypoint. Parses args, runs the service, returns exit code.

    Args:
        argv: Optional argument vector (omit to use sys.argv[1:]).

    Returns:
        0 on success, non-zero on error.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    ns = parser.parse_args(argv)

    try:
        cfg = Config.from_env_and_args(ns)
        cfg.validate()
        configure_logging(cfg.log_level)
        logger.debug("Configuration: %s", cfg)

        repo = FileRepository(input_path=cfg.input_path, output_path=cfg.output_path)
        service = DataService(repo=repo)
        with log_duration("process"):
            count = service.process()
        logger.info("Processed %d unique record(s)", count)
        return 0
    except AppError as exc:
        # Known, user-facing error
        configure_logging(ns.log_level if hasattr(ns, "log_level") else "INFO")
        logger.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception:  # noqa: BLE001 - top-level safety net
        configure_logging(ns.log_level if hasattr(ns, "log_level") else "INFO")
        logger.exception("Unexpected error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
