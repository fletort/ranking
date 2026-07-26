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

**Milestone:** [POC - Phase 2](https://github.com/fletort/ranking/milestone/3)

Goal: make the pipeline observable during real runs

- [x] instrument pipeline with structured logging (fetch, cache, parsing, orchestration)
      [#32](https://github.com/fletort/ranking/issues/32)

## 🚧 Phase 3 — Limited Real Crawl (B+)

**Milestone:** [POC - Phase 3](https://github.com/fletort/ranking/milestone/4)

Goal: validate and stabilize the pipeline on real data

- [x] cli: fetch/parse all event of the first page by default
      [#37](https://github.com/fletort/ranking/issues/37)
- [x] cli: add logging level filter (info by default, --debug to get debug trace too)
      [#38](https://github.com/fletort/ranking/issues/38)
- [x] cli: add event url argument (--event-url) [#39](https://github.com/fletort/ranking/issues/39)
- [x] run the full pipeline on a limited set of events (10–20) and iteratively fix problems
      [#35](https://github.com/fletort/ranking/issues/35)

👉 First real end-to-end validation.

## 🚧 Phase 4 — Extended Crawl (A) & Parsing Stabilization

**Milestone:** [POC - Phase 4](https://github.com/fletort/ranking/milestone/5)

Goal: Validate the scraper on larger datasets and improve robustness based on real observations.

- [x] implement event list pagination [#47](https://github.com/fletort/ranking/issues/47)
- [x] implement race results pagination [#48](https://github.com/fletort/ranking/issues/48)
- [x] add crawl execution summary: [#49](https://github.com/fletort/ranking/issues/49)
  - duration
  - cache hits/misses
  - events processed
  - races processed
  - results processed
  - skipped items
  - failures
- [x] run large-scale validation crawl on local cache and fix problems
      [#50](https://github.com/fletort/ranking/issues/50)
  - identify and fix edge cases discovered during large-scale runs
    - handle missing fields
    - handle format inconsistencies
    - improve parsing robustness

👉 This phase is driven by real data, not anticipation.

## Phase 5 Additional Crawl Artifacts

**Milestone:** [POC - Phase 5](https://github.com/fletort/ranking/milestone/6)

Goal: Manage document discovered in the previous large scale test

- [x] Add a generic download behavior for document
      [#57](https://github.com/fletort/ranking/issues/57)
- [x] Manage Race document download [#59](https://github.com/fletort/ranking/issues/59)
- [x] Manage optionals event documents download [#59](https://github.com/fletort/ranking/issues/59)

## 🚧 Phase 6 — Runtime & Storage

**Milestone:** [POC - Phase 6](https://github.com/fletort/ranking/milestone/7)

Goal: prepare long-term unattended execution

- [x] define storage strategy
- [x] implement S3-backed storage (StorageProvider/LocalStorageProvider/S3StorageProvider)
      [#63](https://github.com/fletort/ranking/issues/63)
- [x] support storage backend selection (local / s3) from CLI
      [#69](https://github.com/fletort/ranking/issues/69)
- [x] add storage diagnostic command [#70](https://github.com/fletort/ranking/issues/70)
- [ ] Valid: restart behavior using persistent storage
  - [x] dev: move lazy pause on real crawl only (faster cache)
        [#66](https://github.com/fletort/ranking/issues/66)
  - [ ] validate cache reuse across crawler restarts (on S3)
- [ ] CI/CD: prepare VM deployment [#67](https://github.com/fletort/ranking/issues/67)
  - [ ] create VM installation script and/or document VM prerequesite
  - [ ] create deployment GitHub Action (manual action)
  - [ ] validate full crawl execution on VM
  - [x] Refactor S3StorageProvider to support multiple S3-compatible backends (added)
        [#76](https://github.com/fletort/ranking/issues/76)

## 🚧 Phase 7 — Incremental Crawling

Goal: Add a technical (plugin) incremental crawl strategy

- [ ] define refresh window strategy (ex: REFRESH_LAST_EVENTS (days ?))
- [ ] define incremental crawl strategy (ex: STOP_AFTER_KNOWN_EVENTS (int))
- [ ] detect new events
- [ ] revisit recent events
- [ ] track crawl state
- [ ] evaluate plugin-oriented persistence

## 🚧 Phase 8 — Parsing & Normalization

Goal: transform extracted data into consistent structured values

- [ ] refine parsing logic based on observed variations
- [ ] extract structured values from raw fields (dates, times, categories, etc.)
- [ ] normalize values into consistent formats (datetime, enums, etc.)
- [ ] handle optional and missing fields explicitly
- [ ] define core entities: Event, Race, Participant, Result with Pydantic models.

👉 This phase bridges raw extraction and the final data model.

## 🔄 Phase 9 — Simple Plugin Structure

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
- document parsing (PDF/XLSX)

[technical-specification]: ./docs/technical_specification.md
