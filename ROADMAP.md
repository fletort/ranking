# Roadmap POC

## POC - Phase 0 — Basic Navigation & Parsing

**Milestone:** [POC - Phase 0](https://github.com/fletort/ranking/milestone/1)

Goal: prove you can traverse a _classical_ site and extract results (first static plugin)

- [x] first generic fetch page method [#3](https://github.com/fletort/ranking/issues/3)
- [x] fetch events list page and extract event informations with their URLs
      [#5](https://github.com/fletort/ranking/issues/5)
- [x] fetch event page and extract event informations and race informations with their URLs
      [#6](https://github.com/fletort/ranking/issues/6)
- [x] fetch race result page and parse results from one race
      [#7](https://github.com/fletort/ranking/issues/7)
- [x] fetch result detail page and parse result information
      [#15](https://github.com/fletort/ranking/issues/15)

## POC - Phase 1 — Simple Cache (MUST HAVE)

**Milestone:** [POC - Phase 1](https://github.com/fletort/ranking/milestone/2)

**Goal:** never re-fetch the same URL

- [x] Implement a class resposible of the Cache v1 as defined in the [technical-specification]
      [#18](https://github.com/fletort/ranking/issues/18)
- [x] Use the cache V1 (developed in #18) in the cli. fetch.py becomes the fetcher_httpx that can be
      used with the cache. [technical-specification].
      [#20](https://github.com/fletort/ranking/issues/20)
- [x] Enable optional persistence of extracted JSON for debugging (see § Development Notes of the
      [technical-specification]) [#21](https://github.com/fletort/ranking/issues/21)

## 🚧 Phase 2 — Observability & Debug (HIGH PRIORITY)

Goal: make the pipeline observable during real runs

- [ ] instrument pipeline with structured logging (fetch, cache, parsing, orchestration)

## 🚧 Phase 3 — Limited Real Crawl (B+)

Goal: validate and stabilize the pipeline on real data

- [ ] run the full pipeline on a limited set of events (10–20) and iteratively

👉 First real end-to-end validation.

## 🚧 Phase 4 — Extended Crawl (A)

Goal: scale data collection

- [ ] implement pagination on event list
- [ ] crawl multiple pages of events
- [ ] validate stability at scale
- [ ] monitor:
  - performance
  - cache efficiency
  - parsing robustness

## 🚧 Phase 5 — Parsing Stabilization

Goal: clean and harden parsing based on real observations

- [ ] handle missing fields
- [ ] handle format inconsistencies
- [ ] improve parsing robustness
- [ ] extend fixtures from real cases

👉 This phase is driven by real data, not anticipation.

## 🚧 Phase 6 — Data Model Definition (D)

Goal: define a stable, shared model

- [ ] define core entities:
  - Event
  - Race
  - Participant
  - Result
- [ ] normalize fields across pages
- [ ] introduce Pydantic models
- [ ] validate extracted data

👉 Only after enough observation (Phases 3–5)

## 🔄 Phase 8 — Simple Plugin Structure

Goal: formalize plugin structure when needed

- [ ] refactor plugin into explicit structure
- [ ] define minimal plugin contract
- [ ] isolate parsing + normalization clearly

👉 Only useful when complexity grows or second plugin appears.

## Future Axes

- plugin abstraction system
- advanced HTTP cache (TTL, policies)
- event-driven runtime
- serverless execution (AWS)
- distributed scraping

[technical-specification]: ./docs/technical_specification.md
