# Document Management POC with FastAPI

A minimal proof-of-concept for a document management system with:

- concurrent uploads using FastAPI
- local disk or object storage for files
- PostgreSQL/SQLite metadata storage
- hybrid synchronous and background processing for text extraction
- text search against extracted document content
- text extraction from TXT, PDF, and DOCX

## Setup

```bash
cd dms-fastapi-poc
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

If you want to use PostgreSQL instead of SQLite, set `DATABASE_URL` before starting the app:

```bash
export DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/dms"
```

By default, uploaded files are stored locally. To use object storage instead, configure the storage backend and S3-compatible bucket:

```bash
export STORAGE_BACKEND="s3"
export S3_BUCKET="your-bucket-name"
export S3_REGION="us-east-1"
# Optional: custom S3-compatible endpoint (MinIO, DigitalOcean Spaces, etc.)
export S3_ENDPOINT_URL="https://play.min.io"
```

This project supports selectable search backends:

- `sql` — basic `ILIKE` search over filename and extracted text
- `tsvector` — PostgreSQL full-text search using `to_tsvector` and `plainto_tsquery`
- `elastic` — external Elasticsearch/OpenSearch indexing and search

Configure the search backend with `SEARCH_BACKEND`:

```bash
export SEARCH_BACKEND="sql"
# or
export SEARCH_BACKEND="tsvector"
# or
export SEARCH_BACKEND="elastic"
export ELASTICSEARCH_HOSTS="http://localhost:9200"
export ELASTICSEARCH_INDEX="documents"
```

If you select `tsvector`, the app will automatically create a GIN index on
PostgreSQL during `init_db()` when it detects a PostgreSQL connection URL.

This project also uses a hybrid processing model:

- small files are processed synchronously during upload
- large files are enqueued for background processing
- the threshold is controlled with `PROCESSING_SYNC_SIZE_LIMIT_BYTES`
- `FORCE_BACKGROUND_PROCESSING=true` forces all uploads into the worker

To run the background worker, install dependencies and start Celery:

```bash
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/1"
celery -A tasks worker --loglevel=info
```

Start the app:

```bash
uvicorn main:app --reload
```

Open the interactive API docs:

- http://127.0.0.1:8000/docs

You can also review the request/response lifecycle in `docs/architecture.md`.

## Versioning

This app supports document versioning with immutable version records and a current-version view for active documents.

- `POST /documents/{id}/versions` creates a new version in the same document group.
- `expected_version_id` can be supplied to guard against stale-version uploads and returns `409` if the current version has changed.
- `GET /documents` returns only current versions.
- `GET /documents/{id}/versions` returns the full version history for a document group.
- Documents now track `group_id`, `version_number`, `is_current`, and `base_version_id`.

## Endpoints

- `POST /token` - obtain a bearer token
- `POST /users` - create a user (first user bootstraps the system; subsequent user creation requires admin authorization)
- `POST /upload` - upload a document
- `POST /documents/{id}/versions` - upload a new version for an existing document
- `POST /documents/{id}/share` - grant another user access to a document group
- `DELETE /documents/{id}/share` - revoke a user's access to a document group
- `GET /documents/{id}/permissions` - list sharing permissions for a document group
- `GET /documents` - list current document versions accessible to the user
- `GET /documents/{id}` - retrieve document metadata for a specific version
- `GET /documents/{id}/versions` - list all versions for a document group
- `GET /search?q=keyword` - search document contents
- `GET /download/{id}` - download a document file

## Notes

- Uploaded files are stored in `uploads/`
- SQLite database file is `app.db`
- Metadata can be stored in PostgreSQL by setting `DATABASE_URL`
- API requests must include an `Authorization: Bearer <token>` header for protected endpoints.
- Version history is preserved for audit and rollback, while `GET /documents` exposes only the latest version of each document.
