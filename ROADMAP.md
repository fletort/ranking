# Roadmap POC

## POC - Phase 0 — Basic Navigation & Parsing

**Milestone:** [POC - Phase 0](https://github.com/fletort/ranking/milestone/1)

Goal: prove you can traverse a _classical_ site and extract results (first static plugin)

- [x] first generic fetch page method [#3](https://github.com/fletort/ranking/issues/3)
- [x] fetch events list page and extract event informations with their URLs
      [#5](https://github.com/fletort/ranking/issues/5)
- [ ] fetch event page and extract event informations and race informations with their URLs
      [#6](https://github.com/fletort/ranking/issues/6)
- [x] fetch race result page and parse results from one race
      [#7](https://github.com/fletort/ranking/issues/7)

## POC - Phase 1 — Simple Cache (MUST HAVE)

**Goal:** never re-fetch the same URL

- [ ] implement local file cache
- [ ] fetch = read cache if exists, else HTTP + save
- [ ] confirm it works offline

## POC - Phase 2 — Clean Parsing

**Goal:** make parsing testable and maintainable

- [ ] separate
  - `fetch`
  - `parse_events`
  - `parse_races`
  - `parse_results`

- [ ] save HTML fixtures
- [ ] write basic tests

## POC - Phase 3 — Simple Plugin

**Goal:** introduce structure (without complexity)

- [ ] implement plugin:

```python
def run():
    events = list_events()
    event = select_one(events)

    races = list_races(event)
    race = select_one(races)

    return get_results(race)
```

## POC - Phase 4 — Pagination

**Goal:** scrape multiple items

- [ ] loop over events
- [ ] loop over races per event
- [ ] fetch all result pages
- [ ] cache every request

## POC - Phase 5 — Stabilization

**Goal:** make scraper reliable

- [ ] handle missing fields
- [ ] handle format inconsistencies
- [ ] improve parsing robustness
- [ ] extend fixtures

## POC - Phase 6 — Incremental Improvements

**Goal:** make things cleaner (no overkill)

- [ ] improve cache structure
- [ ] add basic logging (progress, cache hit)
- [ ] cleanup code

## Future Axes

- plugin abstraction system

- advanced HTTP cache (TTL, policies)
- event-driven runtime
- serverless execution (AWS)
- distributed scraping
