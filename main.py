from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import (
    FORCE_BACKGROUND_PROCESSING,
    PROCESSING_SYNC_SIZE_LIMIT,
    SEARCH_BACKEND,
    STORAGE_BACKEND,
)
from database import get_db, init_db
from models import Document, DocumentPermission, User
from auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_user,
    create_access_token,
    decode_access_token,
    get_current_user,
    get_user,
    hash_password,
)
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


def get_permitted_group_ids(db: Session, user: User):
    if user.role == "admin":
        return None

    owned_groups = [group_id for (group_id,) in db.query(Document.group_id).filter(Document.owner_id == user.id).distinct()]
    shared_groups = [group_id for (group_id,) in db.query(DocumentPermission.group_id).filter(DocumentPermission.user_id == user.id).distinct()]
    return list(set(owned_groups + shared_groups))


def ensure_user_can_access_document(document: Document, user: User, db: Session) -> None:
    if user.role == "admin":
        return
    if document.owner_id == user.id:
        return
    if document.owner and document.owner == user.username:
        return
    permission = (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.group_id == document.group_id,
            DocumentPermission.user_id == user.id,
        )
        .first()
    )
    if permission:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this document.")


@app.on_event("startup")
def on_startup():
    """Initialize the database and any required tables on application startup."""
    init_db()


@app.post("/token")
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/users")
def create_user(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    if role not in {"admin", "editor", "viewer", "user"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role.")

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists.")

    existing_user_count = db.query(User).count()
    if existing_user_count > 0:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required to create users.")
        token = authorization.split(" ", 1)[1]
        payload = decode_access_token(token)
        current_user = get_user(db, payload.get("sub"))
        if not current_user or current_user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required to create users.")

    new_user = User(username=username, hashed_password=hash_password(password), role=role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"username": new_user.username, "role": new_user.role}


@app.post("/upload")
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
        owner=current_user.username,
        owner_id=current_user.id,
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
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a list of the current document versions with basic metadata."""
    query = db.query(Document).filter(Document.is_current == True)
    if current_user.role != "admin":
        permitted_groups = get_permitted_group_ids(db, current_user)
        query = query.filter(
            or_(Document.owner_id == current_user.id, Document.group_id.in_(permitted_groups or []))
        )

    documents = query.order_by(Document.created_at.desc()).all()
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
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return metadata for a single document version by ID."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_user_can_access_document(document, current_user, db)
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
    current_user: User = Depends(get_current_user),
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

    ensure_user_can_access_document(current_doc, current_user, db)

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
        owner_id=current_doc.owner_id,
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
def list_document_versions(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all versions for a document group."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_user_can_access_document(document, current_user, db)

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


@app.post("/documents/{document_id}/share")
def share_document(
    document_id: int,
    username: str = Form(...),
    access_level: str = Form("read"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Grant access to a document group for another user."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if current_user.role != "admin" and document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the document owner or admin can share access.")

    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    if access_level not in {"read", "write"}:
        raise HTTPException(status_code=400, detail="Invalid access level")

    permission = (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.group_id == document.group_id,
            DocumentPermission.user_id == target_user.id,
        )
        .first()
    )
    if permission:
        permission.access_level = access_level
    else:
        permission = DocumentPermission(
            group_id=document.group_id,
            user_id=target_user.id,
            access_level=access_level,
        )
        db.add(permission)

    db.commit()
    return {
        "group_id": document.group_id,
        "username": target_user.username,
        "access_level": permission.access_level,
    }


@app.delete("/documents/{document_id}/share")
def revoke_document_share(
    document_id: int,
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke access to a document group for a user."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if current_user.role != "admin" and document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the document owner or admin can revoke access.")

    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    permission = (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.group_id == document.group_id,
            DocumentPermission.user_id == target_user.id,
        )
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Permission not found")

    db.delete(permission)
    db.commit()
    return {"detail": "Access revoked"}


@app.get("/documents/{document_id}/permissions")
def list_document_permissions(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List sharing permissions for a document group."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if current_user.role != "admin" and document.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the document owner or admin can view permissions.")

    permissions = (
        db.query(DocumentPermission)
        .filter(DocumentPermission.group_id == document.group_id)
        .all()
    )
    return [
        {
            "username": db.query(User).filter(User.id == perm.user_id).first().username,
            "access_level": perm.access_level,
        }
        for perm in permissions
    ]


@app.get("/search")
def search_documents(
    q: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search documents using the configured search backend."""
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter q is required")

    search_backend = get_search_backend()
    permitted_groups = get_permitted_group_ids(db, current_user)
    if current_user.role == "admin":
        documents = search_backend.search(db, q)
    else:
        documents = search_backend.search(db, q, permitted_groups=permitted_groups)

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
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the stored file bytes for a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_user_can_access_document(document, current_user, db)

    try:
        return get_download_response(
            document.storage_backend,
            document.path,
            document.filename,
            document.content_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
