"""Search backend abstraction for SQL, PostgreSQL tsvector, and Elasticsearch."""

from typing import List

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import TransportError
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import (
    ELASTICSEARCH_HOSTS,
    ELASTICSEARCH_INDEX,
    SEARCH_BACKEND,
    SEARCH_LANGUAGE,
)
from models import Document


class SearchBackend:
    """Search backend interface."""

    def search(self, db: Session, query: str) -> List[Document]:
        raise NotImplementedError

    def index_document(self, db: Session, document: Document) -> None:
        raise NotImplementedError


class SQLSearchBackend(SearchBackend):
    """Basic SQL search using ILIKE on filename and search_text."""

    def search(self, db: Session, query: str) -> List[Document]:
        search_term = f"%{query}%"
        return (
            db.query(Document)
            .filter(
                Document.is_current == True,
                Document.filename.ilike(search_term)
                | Document.search_text.ilike(search_term),
            )
            .order_by(Document.created_at.desc())
            .limit(50)
            .all()
        )

    def index_document(self, db: Session, document: Document) -> None:
        return


class TsvectorSearchBackend(SearchBackend):
    """PostgreSQL full-text search using tsvector and tsquery."""

    def search(self, db: Session, query: str) -> List[Document]:
        ts_query = func.plainto_tsquery(SEARCH_LANGUAGE, query)
        vector = func.to_tsvector(
            SEARCH_LANGUAGE,
            func.coalesce(Document.search_text, ""),
        )
        rank = func.ts_rank_cd(vector, ts_query)
        return (
            db.query(Document)
            .filter(Document.is_current == True)
            .filter(vector.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(50)
            .all()
        )

    def index_document(self, db: Session, document: Document) -> None:
        return


class ElasticsearchSearchBackend(SearchBackend):
    """Elasticsearch search backend for external indexing and query."""

    def __init__(self):
        self.client = Elasticsearch(ELASTICSEARCH_HOSTS)
        self.ensure_index()

    def ensure_index(self) -> None:
        if not self.client.indices.exists(index=ELASTICSEARCH_INDEX):
            mapping = {
                "mappings": {
                    "properties": {
                        "group_id": {"type": "keyword"},
                        "document_id": {"type": "integer"},
                        "version_number": {"type": "integer"},
                        "filename": {"type": "text"},
                        "search_text": {"type": "text"},
                    }
                }
            }
            self.client.indices.create(index=ELASTICSEARCH_INDEX, body=mapping)

    def search(self, db: Session, query: str) -> List[Document]:
        search_body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["filename", "search_text"],
                }
            },
            "size": 50,
        }
        try:
            response = self.client.search(index=ELASTICSEARCH_INDEX, body=search_body)
        except TransportError:
            return []

        document_ids = [hit["_source"]["document_id"] for hit in response["hits"]["hits"]]
        documents = (
            db.query(Document)
            .filter(Document.id.in_(document_ids), Document.is_current == True)
            .all()
        )
        return sorted(documents, key=lambda doc: document_ids.index(doc.id))

    def index_document(self, db: Session, document: Document) -> None:
        payload = {
            "group_id": document.group_id,
            "document_id": document.id,
            "version_number": document.version_number,
            "filename": document.filename,
            "search_text": document.search_text or "",
        }
        self.client.index(
            index=ELASTICSEARCH_INDEX,
            id=document.group_id,
            body=payload,
            refresh="wait_for",
        )


def get_search_backend() -> SearchBackend:
    if SEARCH_BACKEND == "tsvector":
        return TsvectorSearchBackend()
    if SEARCH_BACKEND == "elastic":
        return ElasticsearchSearchBackend()
    return SQLSearchBackend()
