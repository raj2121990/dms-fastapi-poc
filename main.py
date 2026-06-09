from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import (
    FORCE_BACKGROUND_PROCESSING,
    PROCESSING_SYNC_SIZE_LIMIT,
    SEARCH_BACKEND,
    STORAGE_BACKEND,
)
from database import get_db, init_db
from models import Document
from search import get_search_backend
from storage import get_download_response, save_to_storage
from tasks import process_document
from utils import (
    extract_text_from_file,
    make_storage_name,
    make_storage_path,
    save_upload_file,
)

app = FastAPI(
    title="Document Management POC",
    description="A simple document upload and search service using FastAPI.",
)


@app.on_event("startup")
def on_startup():
    """Initialize the database and any required tables on application startup."""
    init_db()


@app.post("/upload")
def upload_document(
    file: UploadFile = File(...),
    owner: str = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a new document and create its first version."""
    group_id = uuid4().hex
    version_number = 1

    local_path = make_storage_path(
        file.filename,
        group_id=group_id,
        version_number=version_number,
    )
    save_upload_file(file, local_path)
    size = Path(local_path).stat().st_size

    should_process_sync = (
        not FORCE_BACKGROUND_PROCESSING
        and size <= PROCESSING_SYNC_SIZE_LIMIT
    )

    search_text = None
    status = "pending"
    if should_process_sync:
        search_text = extract_text_from_file(local_path, file.content_type or "")
        status = "processed"

    storage_name = make_storage_name(
        file.filename,
        group_id=group_id,
        version_number=version_number,
    )
    storage_path = save_to_storage(file, local_path, storage_name)
    if STORAGE_BACKEND == "s3":
        try:
            Path(local_path).unlink()
        except OSError:
            pass

    document = Document(
        group_id=group_id,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        owner=owner,
        size=size,
        path=storage_path,
        storage_backend=STORAGE_BACKEND,
        status=status,
        search_text=search_text,
        version_number=version_number,
        is_current=True,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    if status == "pending":
        process_document.delay(document.id)
    elif SEARCH_BACKEND == "elastic":
        get_search_backend().index_document(db, document)

    return {
        "id": document.id,
        "group_id": document.group_id,
        "version_number": document.version_number,
        "filename": document.filename,
        "content_type": document.content_type,
        "owner": document.owner,
        "size": document.size,
        "status": document.status,
        "created_at": document.created_at.isoformat(),
    }


@app.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    """Return a list of the current document versions with basic metadata."""
    documents = (
        db.query(Document)
        .filter(Document.is_current == True)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [
        {
            "id": doc.id,
            "group_id": doc.group_id,
            "version_number": doc.version_number,
            "filename": doc.filename,
            "content_type": doc.content_type,
            "owner": doc.owner,
            "size": doc.size,
            "created_at": doc.created_at.isoformat(),
        }
        for doc in documents
    ]


@app.get("/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Return metadata for a single document version by ID."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": document.id,
        "group_id": document.group_id,
        "version_number": document.version_number,
        "filename": document.filename,
        "content_type": document.content_type,
        "owner": document.owner,
        "size": document.size,
        "path": document.path,
        "storage_backend": document.storage_backend,
        "status": document.status,
        "is_current": document.is_current,
        "error_message": document.error_message,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


@app.post("/documents/{document_id}/versions")
def upload_document_version(
    document_id: int,
    file: UploadFile = File(...),
    expected_version_id: int = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a new version of an existing document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    current_doc = (
        db.query(Document)
        .filter(Document.group_id == document.group_id, Document.is_current == True)
        .first()
    )
    if not current_doc:
        raise HTTPException(status_code=404, detail="Current document version not found")

    if expected_version_id is not None and expected_version_id != current_doc.id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Version mismatch. Upload against latest version only.",
                "current_version_id": current_doc.id,
                "current_version_number": current_doc.version_number,
            },
        )

    new_version_number = current_doc.version_number + 1
    group_id = current_doc.group_id

    local_path = make_storage_path(
        file.filename,
        group_id=group_id,
        version_number=new_version_number,
    )
    save_upload_file(file, local_path)
    size = Path(local_path).stat().st_size

    should_process_sync = (
        not FORCE_BACKGROUND_PROCESSING
        and size <= PROCESSING_SYNC_SIZE_LIMIT
    )

    search_text = None
    status = "pending"
    if should_process_sync:
        search_text = extract_text_from_file(local_path, file.content_type or "")
        status = "processed"

    storage_name = make_storage_name(
        file.filename,
        group_id=group_id,
        version_number=new_version_number,
    )
    storage_path = save_to_storage(file, local_path, storage_name)
    if STORAGE_BACKEND == "s3":
        try:
            Path(local_path).unlink()
        except OSError:
            pass

    current_doc.is_current = False

    document = Document(
        group_id=group_id,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        owner=current_doc.owner,
        size=size,
        path=storage_path,
        storage_backend=STORAGE_BACKEND,
        status=status,
        search_text=search_text,
        version_number=new_version_number,
        is_current=True,
        base_version_id=current_doc.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    if status == "pending":
        process_document.delay(document.id)
    elif SEARCH_BACKEND == "elastic":
        get_search_backend().index_document(db, document)

    return {
        "id": document.id,
        "group_id": document.group_id,
        "version_number": document.version_number,
        "filename": document.filename,
        "content_type": document.content_type,
        "owner": document.owner,
        "size": document.size,
        "status": document.status,
        "created_at": document.created_at.isoformat(),
    }


@app.get("/documents/{document_id}/versions")
def list_document_versions(document_id: int, db: Session = Depends(get_db)):
    """Return all versions for a document group."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    versions = (
        db.query(Document)
        .filter(Document.group_id == document.group_id)
        .order_by(Document.version_number.desc())
        .all()
    )
    return [
        {
            "id": version.id,
            "group_id": version.group_id,
            "version_number": version.version_number,
            "filename": version.filename,
            "content_type": version.content_type,
            "owner": version.owner,
            "size": version.size,
            "status": version.status,
            "is_current": version.is_current,
            "created_at": version.created_at.isoformat(),
        }
        for version in versions
    ]


@app.get("/search")
def search_documents(q: str, db: Session = Depends(get_db)):
    """Search documents using the configured search backend."""
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter q is required")

    search_backend = get_search_backend()
    documents = search_backend.search(db, q)

    return [
        {
            "id": document.id,
            "filename": document.filename,
            "owner": document.owner,
            "size": document.size,
            "status": document.status,
            "matched_snippet": None,
        }
        for document in documents
    ]


@app.get("/download/{document_id}")
def download_document(document_id: int, db: Session = Depends(get_db)):
    """Return the stored file bytes for a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        return get_download_response(
            document.storage_backend,
            document.path,
            document.filename,
            document.content_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
