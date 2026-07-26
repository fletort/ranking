# Runtime Design

This document describes the current runtime implementation and class relationships.

Unlike architectural documents, this design may evolve as new runtime requirements emerge.

## Purpose

The crawler runtime is responsible for:

- applying cache policies
- orchestrating network access
- persisting artifacts
- downloading documents
- delegating storage concerns to a storage backend

The runtime intentionally remains independent from:

- filesystem layout
- S3 implementation
- plugin-specific business logic

Storage concerns are delegated to a `StorageProvider`.

## Main Components

```mermaid
classDiagram

    class HttpxCrawlerRuntime {
        +fetcher(url)
        +downloader(url)
    }

    class CrawlerRuntime {
        <<abstract>>
        +fetch(url, policy)
        +download(url)
        +save_extracted_json(url, data)
        +fetcher(url)
        +downloader(url)
    }

    class AwsS3StorageProvider
    class GcsS3StorageProvider

    class LocalStorageProvider

    class S3StorageProvider {
        _build_client_kwargs()
    }

    class StorageProvider {
        <<abstract>>
        +save_http_cache()
        +get_http_cache()
        +save_http_snapshot()
        +save_extracted()
        +save_document()
        +get_document()
    }

    class DownloadedDocument {
        +url
        +content
        +content_type
        +content_length
        +original_filename
        +downloaded_at
    }

    CrawlerRuntime --> StorageProvider
    HttpxCrawlerRuntime --|> CrawlerRuntime

    LocalStorageProvider --|> StorageProvider
    S3StorageProvider --|> StorageProvider
    AwsS3StorageProvider --|> S3StorageProvider
    GcsS3StorageProvider --|> S3StorageProvider

    StorageProvider --> DownloadedDocument
    HttpxCrawlerRuntime --> DownloadedDocument
```

## Responsibilities

### CrawlerRuntime

Responsible for:

- cache policy application
- cache statistics
- change detection
- document download orchestration
- extracted data persistence

Not responsible for:

- path construction
- S3 key generation
- filesystem management

### HttpxCrawlerRuntime

Responsible for:

- HTTP requests
- redirects
- response validation
- document downloading

Not responsible for:

- storage
- cache persistence

### StorageProvider

Responsible for:

- URL canonicalization
- Resource ID generation
- artifact persistence
- artifact retrieval

Not responsible for:

- HTTP requests
- cache decisions
- parsing

### DownloadedDocument

DownloadedDocument represents the logical document exchanged between2the runtime and the storage
provider. A downloaded document contains:

- content
- metadata
- source URL

The storage backend is responsible for persisting this information.

## Design Rationale

The runtime uses dependency injection:

```text
CrawlerRuntime
    ↓
StorageProvider
```

allowing storage implementations to be replaced without affecting crawler logic.

Examples:

```text
LocalStorageProvider
AwsS3StorageProvider
GcsS3StorageProvider
```

The runtime interacts only with URLs. Concepts such as:

- Resource IDs
- filesystem paths
- S3 object keys

remain internal implementation details of the storage provider.

## S3-Compatible Storage Providers

The runtime supports multiple S3-compatible storage backends.

Common S3 storage behavior is implemented in `S3StorageProvider`.

Provider-specific implementations customize boto3 client configuration through the
`_build_client_kwargs()` extension hook.

Current implementations:

- AwsS3StorageProvider
- GcsS3StorageProvider

This design keeps all storage behavior centralized while allowing provider-specific client
configuration.
