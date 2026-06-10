from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL, SEARCH_BACKEND, SEARCH_LANGUAGE

# Use SQLite-specific engine options only when the configured database URL
# points to a SQLite file. This makes the same code path work for PostgreSQL
# or other SQL databases once DATABASE_URL is updated.
connect_args = {
    "check_same_thread": False,
} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create database tables and any required support structures."""
    from models import Document, User  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # If using PostgreSQL full-text search, create a GIN index on the generated
    # tsvector expression for fast search queries.
    if SEARCH_BACKEND == "tsvector" and DATABASE_URL.startswith("postgresql"):
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_documents_search_vector "
                    "ON documents USING GIN (to_tsvector(:lang, coalesce(search_text, '')));"
                ),
                {"lang": SEARCH_LANGUAGE},
            )
            conn.commit()


def get_db():
    """Provide a SQLAlchemy database session for FastAPI dependencies."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
