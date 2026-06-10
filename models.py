from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<User username={self.username!r} role={self.role!r}>"


class DocumentPermission(Base):
    __tablename__ = "document_permissions"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_document_permission_group_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(String, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    access_level = Column(String, nullable=False, default="read")
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<DocumentPermission group_id={self.group_id!r} user_id={self.user_id} access_level={self.access_level!r}>"


class Document(Base):
    """Document metadata stored in the relational database."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    owner = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    size = Column(Integer, nullable=False)
    path = Column(String, nullable=False)
    storage_backend = Column(String, nullable=False, default="local")
    status = Column(String, nullable=False, default="pending")
    error_message = Column(String, nullable=True)
    search_text = Column(Text, nullable=True)
    version_number = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    base_version_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<Document id={self.id} group_id={self.group_id!r} "
            f"version={self.version_number} filename={self.filename!r}>"
        )
