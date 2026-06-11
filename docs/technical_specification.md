# Technical Specification — Ranking Scraper

## 1. Language & Tooling

| Concern               | Choice              |
| --------------------- | ------------------- |
| Language              | Python 3.12         |
| Dependency management | Poetry              |
| Data validation       | Pydantic v2         |
| HTTP client           | httpx (async-ready) |
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

## 3. CI / CD

- Linting and type checking (`ruff`, `mypy`) run on every push / PR.

- Tests are added progressively as parsing logic stabilizes.
- Coverage (`pytest --cov`) is only enforced once tests are in place.

---

## 4. Principles

- Build incrementally from real use cases
- Avoid over-engineering
- Prefer simple and explicit code
- Extract abstractions only when needed

---

## 5. Parsing Approach

Parsing logic is initially implemented per use case.

Reusable helpers (e.g. table parsing) are extracted only when patterns emerge.
