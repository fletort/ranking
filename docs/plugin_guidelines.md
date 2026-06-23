# Plugin Guidelines

Plugins are responsible for extracting and structuring data from HTML pages.

This document describes how to build maintainable, consistent, and observable plugins.

---

## 1. Purpose

A plugin is responsible for:

- fetching relevant pages (via the core)
- extracting data from HTML
- structuring data progressively

The plugin contains all **site-specific logic**.

---

## 2. Conceptual Model

Parsing typically follows three conceptual levels:

### 2.1 Extraction (required)

Extract raw values directly from HTML (DOM parsing).

Example:

```python
{
    "date_raw": "du 10 juin au 12 juin"
}
```

---

### 2.2 Parsing (optional)

Extract structured information from raw values. Can be combined with the next step.

Example:

```python
{
    "start_date": "2024-06-10",
    "end_date": "2024-06-12"
}
```

---

### 2.3 Normalization (optional)

Convert values into consistent and comparable formats, as defined by the common Model.

Example:

```python
{
    "start_date": datetime(...),
    "end_date": datetime(...)
}
```

---

### Notes

Only normalized output (level 3) is considered "final" The system does not enforce these levels
strictly You may combine steps if it keeps the code simple. The fist step output is very usefull for
debug purpose.

👉 Prefer clarity over purity

---

## 3. Writing a Parser

Start simple and evolve based on real data.

Example:

```python
def extract(html):
    return {
        "title": ...,
        "date_raw": ...,
    }
```

---

### Guidelines

- Prefer simple and explicit code
- Avoid premature abstraction
- Handle missing data gracefully
- Use real HTML examples to guide development

---

## 4. Structured Logging

Structured logging is used to make the scraping pipeline observable and easy to debug.

---

### 4.1 General Rule

All logs must follow the pattern:

```python
logger.<level>("event_name", key=value, ...)
```

- event_name is a stable identifier
- additional data must be structured (key-value pairs)
- avoid free-form strings

❌ Bad:

```python
logger.warning(f"Missing href for link {link}")
```

✅ Good:

```python
logger.warning("missing_data", type="field", name="href", location="race_link")
```

### 4.2 Event Naming Convention

Event names must be:

- lowercase
- snake_case
- stable
- semantic (describe _what happened_)

#### Common categories

| Category  | Examples                     |
| --------- | ---------------------------- |
| actions   | fetch_start, fetch_end       |
| states    | cache_hit, cache_miss        |
| success   | parse_success                |
| failures  | parse_failed                 |
| anomalies | missing_data, invalid_format |
| data      | extracted_data, decoded_data |

---

### 4.3 Standard Fields

Use consistent field names.

#### Generic context

- `url`: current page URL
- `component`: `fetch`, `cache`, `parser`
- `entity`: `event`, `race`, `result`

#### Data context

- `type`: describes the nature of the data being processed:
  - `element`: an HTML element (e.g. `<table>`, `<a>`, `<h1>`)
  - `attribute`: an HTML attribute (e.g. `href`, `onclick`, `class`)
  - `field`: a logical field extracted by the parser (e.g. `name`, `url`, `date_raw`)
- `name`: name of the missing element or field
- `location`: optional, used to provide more granular context within the HTML structure when
  `entity` is not sufficient (e.g. a specific section or element)
- `text`, `href`, `context_text`: optional simple value available in the context

Additional fields may be used to provide context about the outcome of an operation.

When logging quantities, use the `_count` suffix:

- `races_count`
- `results_count`
- `events_count`

Examples:

```python
log.debug(
    "extracted_data",
    type="element",
    name="h1",
    value=race_raw
)

log.debug(
    "extracted_data",
    type="element",
    name="a",
    href="href",
    value="name")

log.debug("parse_success", races_count=len(races))
```

---

### 4.4 Missing Data Convention (IMPORTANT)

All missing data cases must use **one single event**:

Examples:

```python
logger.warning(
    "missing_data",
    type="element",
    name="h1"
)

logger.warning(
    "missing_data",
    type="field",
    name="href",
    location="race_link"
)
```

---

### 4.5 Log Levels

| Level     | Usage                              |
| --------- | ---------------------------------- |
| debug     | detailed extraction steps          |
| info      | normal execution                   |
| warning   | unexpected but non-blocking issues |
| error     | failures preventing processing     |
| exception | exceptions with stack trace        |

---

### 4.6 Where to Log

✅ Log at:

- parsing boundaries
- missing or inconsistent data
- parsing success / failure

❌ Avoid:

- low-level utility functions
- excessive logs inside loops

---

### 4.7 Context Binding

Use structured context:

```python
logger = structlog.get_logger().bind(
    component="parser",
    entity="event_detail",
    url=url,
)
```

All logs will automatically include this context.

---

#### Example

```python
logger = structlog.get_logger().bind(
    component="parser",
    entity="event_detail",
)

logger.info("parse_start")

if h1 is None:
    logger.error("missing_data", type="element", name="h1")
    return None
```

---

## 5. General Principles

- Keep plugins simple and explicit
- Build from real-world data, not assumptions
- Avoid early generalization
- Prefer clarity over abstraction
- Logging should help understanding, not clutter the code
