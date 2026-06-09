import uuid
from pathlib import Path
from pdfminer.high_level import extract_text as pdf_extract_text
from docx import Document as DocxDocument
from config import UPLOAD_DIR

# Ensure the configured upload directory exists before any file operations.
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def make_storage_path(filename: str, group_id: str = None, version_number: int = None) -> str:
    """Create a unique local file path for an uploaded document version."""
    safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
    if group_id and version_number is not None:
        path = UPLOAD_DIR / group_id / f"v{version_number}"
    else:
        path = UPLOAD_DIR
    path.mkdir(parents=True, exist_ok=True)
    return str(path / safe_name)


def make_storage_name(filename: str, group_id: str = None, version_number: int = None) -> str:
    """Create a storage-safe object key for a document version."""
    safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
    if group_id and version_number is not None:
        return f"{group_id}/v{version_number}/{safe_name}"
    return safe_name


def extract_text_from_file(file_path: str, content_type: str) -> str:
    """Extract text from supported file types for search indexing."""
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf" or content_type == "application/pdf":
        # PDF extraction uses pdfminer.six.
        return pdf_extract_text(file_path)

    if ext == ".docx" or content_type in [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ]:
        # DOCX extraction appends all paragraph text.
        doc = DocxDocument(file_path)
        return "\n".join(paragraph.text for paragraph in doc.paragraphs)

    if ext == ".txt" or content_type.startswith("text/"):
        # Plain text files are read directly.
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")

    # Unsupported file types return no text.
    return ""


def save_upload_file(upload_file, destination: str):
    """Write uploaded file content to a destination file path."""
    upload_file.file.seek(0)
    with open(destination, "wb") as buffer:
        for chunk in upload_file.file:
            buffer.write(chunk)
