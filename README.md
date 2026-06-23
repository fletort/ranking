# RANKING

## Purpose

Ranking is a scraper for race results websites.

It navigates event pages, extracts structured results, and stores them locally. The goal is to build
a reliable and extensible pipeline incrementally.

---

## 🚀 Current Status

This repository follows a **POC-first approach**:

- Start with a working scraper for a real website
- Add features step by step (cache, parsing, traversal)
- Keep architecture simple and evolve only when needed

---

## 🧭 Roadmap

See [ROADMAP.md](./ROADMAP.md)

---

## 🛠 Setup

```bash
poetry install
```

## ▶️ Usage

Run the scraper (example):

```bash
poetry run ranking
```

## 📂 Project Structure

```text
src/ranking/
  core/         # fetch, generic parsing, helpers
  plugins/      # site-specific scrapers

tests/          # parsing tests (fixtures-based)
cache/          # local HTTP cache
```

See [Technical Specification](./docs/technical_specification.md) for detailed project structure.

## 🧪 Testing

```bash
pytest
```

- Use saved HTML fixtures
- Avoid real HTTP calls in tests

## ⚙️ Philosophy

- Build incrementally
- Avoid over-engineering
- Focus on real data

See [Technical Specification](./docs/technical_specification.md) for details.

## Writing a Plugin

See [Plugin Guidelines](docs/plugin_guidelines.md)

## 🔮 Future Direction

_These features will be introduced progressively as real needs emerge._

- Improved caching strategies
- Plugin system abstraction
- Scalable execution (runtime / serverless)
- Multi-source data aggregation
