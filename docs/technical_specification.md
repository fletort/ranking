# Technical Specification — Ranking Scraper

## 1. Language & Tooling

| Concern               | Choice              |
| --------------------- | ------------------- |
| Language              | Python 3.12         |
| Dependency management | Poetry              |
| Data validation       | Pydantic v2         |
| HTTP client           | httpx (async-ready) |
| Web extraction        | beautifulsoup4      |
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

## 3. HTTP Cache - v1

### Purpose

The cache avoids re-fetching already downloaded HTTP resources during scraping. It enables offline
replay, safe background execution, and predictable behavior.

The cache is **not** a performance optimization layer and **not** a data storage system.

---

### Scope

Cache v1 applies only to **raw HTTP responses** (HTML or text content).

The cache stores raw HTTP responses and remains agnostic of content semantics.

However, when using REFRESH_AND_CACHE, a plugin-provided normalization step may be applied before
comparing the fetched content with the cached version to determine whether a snapshot should be
created.

This normalization is not persisted and is used only for change detection purposes.

---

### Cache Policies

Cache behavior is explicitly defined at call time.

Supported policies:

- **NO_CACHE**
  - Always fetch from the network.
  - No cache read or write.
  - Used when fresh data is required and caching is undesirable.

- **CACHE_IF_PRESENT**
  - Use cached content if available.
  - Otherwise fetch and store the response.
  - Used for stable pages (results, detail pages).

- **REFRESH_AND_CACHE**
  - Always fetch from the network.
  - Overwrite the active cache entry.
  - Keep a timestamped snapshot for debugging **only when the fetched content differs from the**
    **currently cached version**.
  - Used for pages that must be refreshed regularly but still need replayability (e.g. event listing
    pages).

Cache decisions are **never implicit**.

---

### API

```python
fetch_page(url: str, cache_policy: CachePolicy) -> str
```

### Storage Strategy

The cache is disk-based and organized as follows:

```text
.cache/
  plugin_name/
    http/
      current/
        1c/
          1c4230b146f1e14eae42b75a7b64f117e561dea7.html
        25/
          252659e0ea47a78c24a82acf647450add45ac9b3.html
      snapshots/
        1c/
          1c4230b146f1e14eae42b75a7b64f117e561dea7/
            2026-06-08T10-12-03.html
```

- One URL maps to one deterministic cache key (see dedicted chapter below).
- The current/ entry represents the active cached version.
- snapshots/ are written only when using REFRESH_AND_CACHE and only when content changes to avoid
  redundant versions.
- Snapshots are never read automatically and exist solely for debugging and inspection purposes.
- To avoid large flat directories, cache entries may be sharded using a prefix derived from the
  cache hash (e.g. the first two hexadecimal characters).

Cache entries are identified exclusively by their hash.

### Cache Key Derivation

Each cached resource is identified by a deterministic cache key derived from the request URL.

- The cache key is computed from a **canonicalized full URL**, including query parameters.
- Query parameters are parsed and sorted by key before rebuilding the URL, so semantically
  equivalent URLs map to the same cache key.
- The hashing algorithm used in v1 is **SHA‑1**, applied to the UTF‑8 encoded URL.
- The resulting hexadecimal digest is used as the cache file name.

The primary goal of the cache key is **deterministic mapping**, not cryptographic security.

The hash generation logic must remain stable across runs to ensure cache reusability.

### Behavioral Rules

- Snapshot creation is based on comparison of normalized content when a normalization plugin is
  provided.
- Raw content is always stored without modification.

### Non-Goals (v1)

- HTTP cache headers (ETag, Cache-Control, etc.)
- Time-based expiration (TTL)
- Partial invalidation
- Concurrency or distributed cache

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

### Extracted JSON Persistence

During development, extracted (pre-normalized) JSON outputs may be persisted alongside the HTTP
cache to support parsing debugging and offline replay.

This JSON persistence is optional and does not represent a storage layer or a long-term data
contract.

This JSON persistence is disk-based and organized as follows (in a extraceted directory alongside
the cache):

```text
.cache/
  plugin_name/
    http/ ## See upper
    extracted/
      1C/
        1c4230b146f1e14eae42b75a7b64f117e561dea7.json
      25/
        252659e0ea47a78c24a82acf647450add45ac9b3.json
```
