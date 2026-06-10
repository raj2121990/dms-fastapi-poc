# Improvements and Scaling Roadmap

## Current Bottlenecks

1. **Single Celery Worker** — Document processing is serialized; large queues block other tasks.
2. **Database Contention** — PostgreSQL can become a bottleneck under high metadata load.
3. **Elasticsearch Overhead** — Full-text indexing latency for every document processed.
4. **Storage Latency** — Local disk I/O or S3 upload/download can slow document ingestion.
5. **Synchronous Upload Path** — Small file processing blocks the API thread.

## Scaling Improvements

### Short-term (Before 10K docs/day)

- **Connection Pooling**: Increase `sqlalchemy.pool_size` and `pool_pre_ping=True` for PostgreSQL.
- **Read Replicas**: Use read-only PostgreSQL replicas for search queries and document listing.
- **Caching Layer**: Add Redis for frequently accessed documents and search results.
- **Batch Indexing**: Queue multiple documents for Elasticsearch bulk indexing instead of one-by-one.
- **Async Cleanup**: Move file temporary cleanup to a separate worker task.

### Medium-term (10K–100K docs/day)

- **Replace Celery with Kafka**:
  - Kafka topics: `document-uploads`, `text-extraction`, `search-indexing`.
  - Consumers can scale independently per topic.
  - Built-in durability, replay, and partition-based load balancing.
  - Native support for multi-DC failover.

- **Document Processing Pipeline**:
  ```
  Upload → Kafka (document-uploads) → File Storage Worker → Kafka (text-extraction) 
    → Text Extraction Worker → Kafka (search-indexing) → Elasticsearch Indexer
  ```

- **API Instance Scaling**:
  - Deploy multiple FastAPI instances behind a load balancer.
  - Use a shared PostgreSQL instance with connection pooling (PgBouncer).
  - Store session state in Redis if needed.

- **Distributed Search**:
  - Elasticsearch cluster with multiple nodes and replicas.
  - Use scroll cursors for pagination instead of offset queries.

### Long-term (100K–1M docs/day)

- **Message Queue Scaling**:
  - Run Kafka cluster with multiple brokers.
  - Partition topics by document type, owner, or storage backend.
  - Monitor lag and auto-scale consumer groups.

- **Multi-Region Deployment**:
  - Replicate PostgreSQL to read-only standby regions.
  - Use S3 cross-region replication.
  - Deploy Elasticsearch clusters in each region.

- **Versioning Optimization**:
  - Store deltas between versions instead of full copies.
  - Implement content-addressable storage (content hash deduplication).
  - Archive old versions to cold storage (e.g., Glacier).

- **Advanced Observability**:
  - Distributed tracing (Jaeger, Datadog).
  - Prometheus metrics for queue depth, indexing latency, API response times.
  - Alert on processing failures and SLA breaches.

## Feature Enhancements

### Document Processing

- **OCR Support**: Integrate Tesseract or cloud OCR for image-based documents.
- **Incremental Extraction**: For large PDFs, extract pages in parallel.
- **Metadata Extraction**: Automatically extract author, creation date, custom fields.
- **Virus Scanning**: Integrate ClamAV or VirusTotal before storing uploads.

### Search and Analytics

- **Faceted Search**: Add category, owner, date range filters.
- **Search Analytics**: Track popular queries and failed searches.
- **Fuzzy Matching**: Handle typos and alternate spellings.
- **Advanced Queries**: Support Boolean operators, phrase search, proximity.

### Reliability

- **Dead-Letter Queues**: Route failed processing tasks for manual review.
- **Circuit Breakers**: Gracefully degrade if Elasticsearch is unavailable.
- **Retry Policies**: Exponential backoff for transient failures.
- **Health Checks**: Document extraction success rate, storage availability, search latency.

### User Experience

- **Progress Tracking**: WebSocket-based upload progress and processing status.
- **Webhooks**: Notify external systems when a document is processed.
- **Preview Generation**: Create thumbnails or excerpts for quick browsing.
- **Bulk Operations**: Upload multiple files, bulk delete, batch reindex.

## Security and Access Control

> Security should be treated as a baseline requirement, even for a small-scale deployment. Authentication and access control are essential before exposing any upload/search APIs.

- **Authentication**: Add token-based auth (JWT/OAuth2) or API key support for all endpoints.
- **Authorization**: Implement role-based access control (RBAC) for users such as admin, editor, viewer, and auditor.
- **Document-level ACLs**: Enforce per-document permissions so owners and collaborators can access only allowed documents.
- **Audit Logging**: Record access, upload, download, and version operations for compliance.
- **Endpoint protection**: Require auth for upload, versioning, search, and document retrieval endpoints.
- **Storage security**: Lock down S3 bucket policies and use server-side encryption for stored files.
- **Secure search**: Ensure search results are filtered by user permissions before returning hits.
- **Rate limiting and throttling**: Protect API endpoints against abuse.

## Infrastructure Considerations

| Layer | Current | Recommended (Scaling) |
|-------|---------|----------------------|
| **API Server** | Single instance | Load-balanced multi-instance |
| **Queue** | Celery + Redis | Kafka cluster |
| **Database** | PostgreSQL | PostgreSQL + read replicas |
| **Cache** | None | Redis cluster |
| **Search** | Elasticsearch | Elasticsearch cluster + replicas |
| **Storage** | S3 or local disk | S3 with versioning + Glacier archive |
| **Monitoring** | Logs only | Prometheus + Grafana + Jaeger |
| **Deployment** | Manual/VM | Docker + Kubernetes |

## Implementation Priority

1. **Phase 1**: Connection pooling, caching, read replicas.
2. **Phase 2**: Kafka integration, bulk indexing, auto-scaling.
3. **Phase 3**: Multi-region, delta storage, advanced search.
4. **Phase 4**: OCR, webhooks, observability stack.

## Sample Kafka Architecture

```
FastAPI Instance 1 \
FastAPI Instance 2 -- POST /upload --> Kafka Topic: document-uploads
FastAPI Instance 3 /                           |
                                               v
                            Consumer Group: file-storage-workers
                                  Worker 1 | Worker 2 | Worker 3
                                               |
                                Kafka Topic: text-extraction
                                               |
                            Consumer Group: text-extraction-workers
                                  Worker A | Worker B | Worker C
                                               |
                                Kafka Topic: search-indexing
                                               |
                            Consumer Group: elasticsearch-indexers
                                  Indexer 1 | Indexer 2
                                               |
                                       Elasticsearch Cluster
```

Each stage is decoupled, independently scalable, and provides durability and replay capability.
