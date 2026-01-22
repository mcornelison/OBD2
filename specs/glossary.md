# Glossary

## Overview

This document defines terms, acronyms, and domain-specific language used in this project. Keep definitions concise and practical.

**Last Updated**: [Date]

---

## Terms

### A

**Acceptance Criteria**
: Specific, verifiable conditions that must be met for a user story to be considered complete. Each criterion should be testable with a YES/NO answer.

**Anti-pattern**
: A common solution to a problem that is ineffective or counterproductive. Documented to help developers avoid known pitfalls.

### B

**Backlog**
: A prioritized list of tasks and features to be implemented. Stored in `specs/backlog.json`.

### C

**camelCase**
: Naming convention where words are joined without spaces, first word lowercase, subsequent words capitalized. Example: `getUserData`, `recordCount`. Used for Python functions and variables in this project.

**Configuration-driven**
: Design pattern where behavior is controlled by external configuration files rather than hardcoded values. Enables flexibility without code changes.

### D

**Dependency Injection**
: Design pattern where dependencies are passed to a component rather than created internally. In this project, configuration is injected as a dictionary parameter.

### E

**Exponential Backoff**
: Retry strategy where wait time increases exponentially with each attempt. Example: 1s, 2s, 4s, 8s, 16s. Used for handling transient failures.

### F

**Fail Fast**
: Design principle where errors are detected and reported as early as possible, typically at startup. Configuration errors should fail fast with clear messages.

### I

**Idempotent**
: An operation that produces the same result regardless of how many times it is executed. Critical for reliable ETL pipelines and retry logic.

### P

**PascalCase**
: Naming convention where words are joined without spaces, each word capitalized. Example: `ConfigValidator`, `DataProcessor`. Used for Python classes in this project.

**PII (Personally Identifiable Information)**
: Data that can identify an individual, such as names, email addresses, SSNs. Must be masked in logs and protected in storage.

**PRD (Product Requirements Document)**
: A document that describes what a feature should do, including goals, user stories, and acceptance criteria. Stored in `specs/tasks/`.

### R

**Ralph**
: The autonomous agent system used for executing user stories. Spawns fresh Claude instances per iteration with no memory between runs.

**Retryable Error**
: An error caused by transient conditions (network timeout, rate limit) that may succeed if attempted again. Should use exponential backoff.

### S

**snake_case**
: Naming convention where words are joined with underscores, all lowercase. Example: `user_accounts`, `created_at`. Used for SQL tables and columns in this project.

**Skill**
: A documented procedure for accomplishing a specific task. Skills define inputs, process steps, and expected outputs. Stored as `*_skill.md` files.

### T

**TDD (Test-Driven Development)**
: Development methodology where tests are written before implementation code. The cycle is: write failing test → write code to pass → refactor.

**Token Budget**
: The maximum number of tokens available for a task in an LLM context window. User stories must fit within the token budget (typically 150K-175K tokens).

### U

**User Story**
: A description of a feature from the user's perspective, following the format: "As a [user], I want [feature] so that [benefit]."

---

## Acronyms

| Acronym | Meaning |
|---------|---------|
| API | Application Programming Interface |
| CLI | Command Line Interface |
| CI/CD | Continuous Integration / Continuous Deployment |
| DDL | Data Definition Language (SQL schema statements) |
| DRY | Don't Repeat Yourself |
| ETL | Extract, Transform, Load |
| JSON | JavaScript Object Notation |
| LLM | Large Language Model |
| OAuth | Open Authorization |
| PII | Personally Identifiable Information |
| PRD | Product Requirements Document |
| REST | Representational State Transfer |
| SCD | Slowly Changing Dimension |
| SQL | Structured Query Language |
| TDD | Test-Driven Development |
| UTC | Coordinated Universal Time |

---

## Adding New Terms

When adding a new term:
1. Place it alphabetically within the appropriate section
2. Use the definition list format (term on one line, definition with `: ` prefix on next)
3. Keep definitions concise (1-2 sentences)
4. Include an example if it helps clarify
5. Update the "Last Updated" date

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| [Date] | [Name] | Initial glossary |
