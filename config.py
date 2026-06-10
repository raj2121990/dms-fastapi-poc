"""Configuration values for the document management application."""

import os
from pathlib import Path

# Local fallback values. These can be overridden by environment variables.
DEFAULT_DATABASE_URL = "sqlite:///./app.db"
DEFAULT_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
DEFAULT_STORAGE_BACKEND = "local"
DEFAULT_PROCESSING_SYNC_SIZE_LIMIT = 2 * 1024 * 1024

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DEFAULT_UPLOAD_DIR)))
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", DEFAULT_STORAGE_BACKEND).lower()
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
PROCESSING_SYNC_SIZE_LIMIT = int(
    os.getenv("PROCESSING_SYNC_SIZE_LIMIT_BYTES", DEFAULT_PROCESSING_SYNC_SIZE_LIMIT)
)
FORCE_BACKGROUND_PROCESSING = os.getenv("FORCE_BACKGROUND_PROCESSING", "false").lower() in (
    "1",
    "true",
    "yes",
)
DEFAULT_SEARCH_BACKEND = "sql"
SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", DEFAULT_SEARCH_BACKEND).lower()
SEARCH_LANGUAGE = os.getenv("SEARCH_LANGUAGE", "english")
ELASTICSEARCH_HOSTS = os.getenv("ELASTICSEARCH_HOSTS", "http://localhost:9200").split(",")
ELASTICSEARCH_INDEX = os.getenv("ELASTICSEARCH_INDEX", "documents")

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
TOKEN_ALGORITHM = os.getenv("TOKEN_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
