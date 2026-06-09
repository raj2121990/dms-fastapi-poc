from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from datetime import datetime
from database import Base


class Document(Base):
    """Document metadata stored in the relational database."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    owner = Column(String, nullable=True)
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
