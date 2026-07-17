# Technical Specification — Ranking Scraper

## 1. Language & Tooling

| Concern               | Choice              |
| --------------------- | ------------------- |
| Language              | Python 3.12         |
| Dependency management | Poetry              |
| Data validation       | Pydantic v2         |
| HTTP client           | httpx (async-ready) |
| Web extraction        | beautifulsoup4      |
| Cli management        | click               |
| Log                   | structlog           |
| Linter / formatter    | ruff                |
| Type checker          | mypy                |
| Tests                 | pytest + pytest-cov |

---

## 2. Repository Layout

```text
ranking/
├── src/
│   └── ranking/
│       ├── __init__.py
│       ├── cli.py                        # CLI entry point
│       ├── core/
│       └── plugins/
│           └── demo/                     # Plugin skeleton
│               ├── __init__.py
│               └── plugin.py
├── tests/
├── docs/
├── ROADMAP.md
├── README.md
├── .github/workflows/ci.yml
├── pyproject.toml
└── .gitignore
```

---

## 3. HTTP Resource Cache

### Purpose

The crawler relies on a resource cache to avoid unnecessary network requests and to support offline
replay.

Storage layout, persistence strategy, URL identity, and backend implementations are defined in:

- docs/storage_strategy.md

### Cache Policies

Supported policies:

- NO_CACHE
- CACHE_IF_PRESENT
- REFRESH_AND_CACHE

Cache decisions are always explicit.

### API

```python
fetch_page(url: str, cache_policy: CachePolicy) -> str
```

## 4. CI / CD

- Linting and type checking (`ruff`, `mypy`) run on every push / PR.

- Tests are added progressively as parsing logic stabilizes.
- Coverage (`pytest --cov`) is only enforced once tests are in place.

---

## 5. Principles

- Build incrementally from real use cases
- Avoid over-engineering
- Prefer simple and explicit code
- Extract abstractions only when needed

---

## 6. Parsing Approach

Parsing logic is initially implemented per use case.

Reusable helpers (e.g. table parsing) are extracted only when patterns emerge.

## 7. Development Notes (Non-Normative)

The following elements are intended to support development, debugging, and experimentation. They are
not part of the core architecture and may be modified or removed without affecting the system
design.

### Structured Logging (Observability)

The scraping pipeline may emit structured logs to support debugging and understanding of real-world
runs.

Logging is intended to provide visibility into key steps of the pipeline, such as:

- HTTP fetching
- cache usage (hit/miss)
- snapshot creation
- parsing success or failure

Logs are structured as key-value events (e.g. using `structlog`) to allow both human readability and
machine processing.

Logging is considered a development and operational aid. It does not affect functional behavior and
may evolve without impacting the core architecture. ``

## 8. References

- storage_strategy.md
- plugin_guidelines.md
- testing/functional-tests.m
