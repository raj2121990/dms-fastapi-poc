import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config import ACCESS_TOKEN_EXPIRE_MINUTES, SECRET_KEY, TOKEN_ALGORITHM
from database import get_db
from models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def _base64_url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _base64_url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
    return f"{_base64_url_encode(salt)}${_base64_url_encode(hashed)}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        salt_b64, hash_b64 = hashed_password.split("$")
    except ValueError:
        return False

    salt = _base64_url_decode(salt_b64)
    expected_hash = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        200000,
    )
    return hmac.compare_digest(expected_hash, _base64_url_decode(hash_b64))


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    now = datetime.utcnow()
    expires = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload.update({"iat": int(now.timestamp()), "exp": int(expires.timestamp())})

    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    encoded_header = _base64_url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _base64_url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"{encoded_header}.{encoded_payload}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded_signature = _base64_url_encode(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"{encoded_header}.{encoded_payload}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, _base64_url_decode(encoded_signature)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token signature.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = json.loads(_base64_url_decode(encoded_payload).decode("utf-8"))
    if "exp" not in payload or int(payload["exp"]) < int(datetime.utcnow().timestamp()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def get_user(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user(db, username)
    if not user:
        return None
    return user if verify_password(password, user.hashed_password) else None


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    payload = decode_access_token(token)
    user = get_user(db, payload.get("sub"))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required.")
    return current_user
