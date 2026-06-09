"""Background worker tasks for document processing."""

from pathlib import Path
from uuid import uuid4

from celery import Celery
from celery.utils.log import get_task_logger
from sqlalchemy.orm import sessionmaker

from config import (
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    SEARCH_BACKEND,
    STORAGE_BACKEND,
    UPLOAD_DIR,
)
from database import engine
from models import Document
from search import get_search_backend
from storage import download_from_s3_to_path
from utils import extract_text_from_file

logger = get_task_logger(__name__)
celery_app = Celery(
    "tasks",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)
celery_app.conf.task_default_queue = "documents"
SessionLocal = sessionmaker(bind=engine)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_document(self, document_id: int):
    """Background task that extracts text and updates document metadata."""
    session = SessionLocal()
    document = None
    temp_path = None
    try:
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("Document %s not found for processing", document_id)
            return

        if document.status == "processed":
            logger.info("Document %s already processed", document_id)
            return

        if document.storage_backend == "s3":
            temp_path = UPLOAD_DIR / f"worker_{uuid4().hex}_{document.filename}"
            download_from_s3_to_path(document.path, str(temp_path))
            source_path = str(temp_path)
        else:
            source_path = document.path

        document.search_text = extract_text_from_file(source_path, document.content_type or "")
        document.status = "processed"
        document.error_message = None
        session.commit()

        if SEARCH_BACKEND == "elastic":
            search_backend = get_search_backend()
            search_backend.index_document(session, document)

        logger.info("Document %s processed successfully", document_id)
    except Exception as exc:
        if document is not None:
            document.status = "failed"
            document.error_message = str(exc)
            session.commit()
        logger.exception("Failed to process document %s", document_id)
        raise self.retry(exc=exc)
    finally:
        session.close()
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                logger.warning("Failed to remove temporary worker file %s", temp_path)
