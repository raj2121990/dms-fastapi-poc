"""Storage backend abstraction for local disk and S3-compatible object storage."""

from pathlib import Path
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from config import (
    S3_BUCKET,
    S3_ENDPOINT_URL,
    S3_REGION,
    STORAGE_BACKEND,
    UPLOAD_DIR,
)


class StorageError(Exception):
    """Raised when a storage backend operation fails."""


def _get_s3_client():
    import boto3

    client_kwargs = {}
    if S3_REGION:
        client_kwargs["region_name"] = S3_REGION
    if S3_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = S3_ENDPOINT_URL

    return boto3.client("s3", **client_kwargs)


def upload_to_s3(local_path: str, object_name: str, content_type: str) -> str:
    """Upload a local file to an S3-compatible bucket."""
    if not S3_BUCKET:
        raise StorageError("S3_BUCKET must be configured for object storage.")

    client = _get_s3_client()
    try:
        with open(local_path, "rb") as data:
            client.upload_fileobj(
                data,
                S3_BUCKET,
                object_name,
                ExtraArgs={"ContentType": content_type or "application/octet-stream"},
            )
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Failed to upload file to S3: {exc}") from exc

    return object_name


def download_from_s3(object_name: str, filename: str, content_type: str):
    """Stream a file back from an S3-compatible bucket."""
    if not S3_BUCKET:
        raise StorageError("S3_BUCKET must be configured for object storage.")

    client = _get_s3_client()
    try:
        s3_object = client.get_object(Bucket=S3_BUCKET, Key=object_name)
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Failed to download file from S3: {exc}") from exc

    response = StreamingResponse(
        s3_object["Body"],
        media_type=content_type or "application/octet-stream",
    )
    response.headers[
        "Content-Disposition"
    ] = f'attachment; filename="{filename}"'
    return response


def save_to_storage(upload_file: UploadFile, local_path: str, storage_name: str) -> str:
    """Save an uploaded file to the configured storage backend.

    The file is first written to a local temporary path for extraction and
    validation. For object storage, the same local file is then uploaded to S3.
    """
    if STORAGE_BACKEND == "s3":
        # Upload the file to S3 and store the object key in the metadata.
        return upload_to_s3(local_path, storage_name, upload_file.content_type or "")

    # Persist the file on local disk and return its file path.
    return local_path


def download_from_s3_to_path(object_name: str, destination_path: str) -> str:
    """Download an object from S3-compatible storage into a local file path."""
    if not S3_BUCKET:
        raise StorageError("S3_BUCKET must be configured for object storage.")

    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    client = _get_s3_client()
    try:
        with open(destination, "wb") as output_file:
            client.download_fileobj(S3_BUCKET, object_name, output_file)
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Failed to download file from S3: {exc}") from exc

    return str(destination)


def get_download_response(storage_backend: str, path: str, filename: str, content_type: str):
    """Return the correct file response for the configured storage backend."""
    if storage_backend == "s3":
        return download_from_s3(path, filename, content_type)

    return FileResponse(path=path, filename=filename)
