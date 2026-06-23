# Contributing

This project is developed incrementally from real-world scraping use cases. Keep things simple and
pragmatic.

## Principles

- Avoid over-engineering
- Prefer explicit and simple code
- Extract abstractions only when needed

## Architecture Guidelines

- The cache stores raw HTTP responses and must remain deterministic
- Plugins contain all site-specific logic (parsing, normalization)
- The CLI orchestrates the workflow

Do not mix responsibilities between layers.

## Logging

Structured logging is used to make the pipeline observable.

- Use structured logs: `logger.info("event_name", key=value)`
- Do not use free-form strings or prints
- Log at the boundaries of major steps:
  - fetch
  - cache
  - parsing

Log levels:

- `info`: normal execution
- `warning`: unexpected but non-blocking issues
- `error`: failures preventing correct processing

## Parsing

- Start simple and evolve based on real data
- Do not over-generalize early
- Use real HTML examples when stabilizing parsing
