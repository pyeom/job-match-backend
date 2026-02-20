"""Elasticsearch service for job discovery.

Provides fast kNN vector search to replace the 25x PostgreSQL candidate
multiplier in GET /jobs/discover.  ES handles vector similarity efficiently
so the Python layer only needs to score a small candidate pool (<= limit x 5).

Index: jobs_v1
  job_id        keyword   - UUID string (mirrors PostgreSQL jobs.id)
  company_id    keyword
  tags          keyword[]
  seniority     keyword
  location      keyword
  remote        boolean
  is_active     boolean
  created_at    date
  job_embedding dense_vector(384, cosine, indexed=True)
"""
import logging
from typing import Any, Optional

from elasticsearch import AsyncElasticsearch, NotFoundError

from app.core.config import settings

logger = logging.getLogger(__name__)

INDEX_NAME = "jobs_v1"
EMBEDDING_DIMS = 384

INDEX_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "job_id":        {"type": "keyword"},
            "company_id":    {"type": "keyword"},
            "tags":          {"type": "keyword"},
            "seniority":     {"type": "keyword"},
            "location":      {"type": "keyword"},
            "remote":        {"type": "boolean"},
            "is_active":     {"type": "boolean"},
            "created_at":    {"type": "date"},
            "job_embedding": {
                "type":       "dense_vector",
                "dims":       EMBEDDING_DIMS,
                "index":      True,
                "similarity": "cosine",
            },
        }
    },
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,  # single-node dev; increase in production
    },
}


class ElasticsearchService:
    """Async wrapper around the Elasticsearch client for job indexing/search."""

    def __init__(self) -> None:
        self._client: Optional[AsyncElasticsearch] = None

    @property
    def client(self) -> AsyncElasticsearch:
        if self._client is None:
            self._client = AsyncElasticsearch(
                settings.elasticsearch_url,
                request_timeout=10,
                retry_on_timeout=True,
                max_retries=3,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying Elasticsearch HTTP transport."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    async def ensure_index(self) -> bool:
        """Create the jobs index if it does not already exist.

        Returns True if the index was just created (needs bulk reindex),
        False if it already existed.
        """
        try:
            exists = await self.client.indices.exists(index=INDEX_NAME)
            if not exists:
                await self.client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)
                logger.info("Created Elasticsearch index: %s", INDEX_NAME)
                return True
            else:
                logger.info("Elasticsearch index already exists: %s", INDEX_NAME)
                return False
        except Exception as exc:
            logger.error("Failed to ensure Elasticsearch index: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Document operations
    # ------------------------------------------------------------------

    async def index_job(self, job: Any) -> None:
        """Index (or update) a job document.

        job is a SQLAlchemy Job model instance.  If the job has no embedding
        it is silently skipped — it will be picked up later once an embedding
        is generated.
        """
        if job.job_embedding is None:
            logger.debug("Skipping ES index for job %s — no embedding", job.id)
            return

        doc: dict[str, Any] = {
            "job_id":        str(job.id),
            "company_id":    str(job.company_id),
            "tags":          job.tags or [],
            "seniority":     job.seniority,
            "location":      job.location,
            "remote":        job.remote or False,
            "is_active":     job.is_active,
            "created_at":    job.created_at.isoformat() if job.created_at else None,
            "job_embedding": list(job.job_embedding),
        }

        try:
            await self.client.index(
                index=INDEX_NAME,
                id=str(job.id),
                document=doc,
            )
            logger.debug("Indexed job %s in Elasticsearch", job.id)
        except Exception as exc:
            logger.error("Failed to index job %s in Elasticsearch: %s", job.id, exc)
            raise

    async def update_job_active_status(self, job_id: str, is_active: bool) -> None:
        """Flip is_active on an existing ES document (used on soft-delete)."""
        try:
            await self.client.update(
                index=INDEX_NAME,
                id=job_id,
                doc={"is_active": is_active},
            )
        except NotFoundError:
            pass  # Document not yet indexed — nothing to update
        except Exception as exc:
            logger.error(
                "Failed to update is_active for job %s in Elasticsearch: %s",
                job_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Discovery search
    # ------------------------------------------------------------------

    async def knn_discover(
        self,
        user_embedding: list[float],
        exclude_job_ids: list[str],
        k: int,
    ) -> list[str]:
        """Run a kNN search over active, non-swiped jobs.

        Returns a list of job_id strings ordered by cosine similarity
        (highest first).  At most *k* results are returned.
        """
        if exclude_job_ids:
            knn_filter: dict[str, Any] = {
                "bool": {
                    "must": {"term": {"is_active": True}},
                    "must_not": {"terms": {"job_id": exclude_job_ids}},
                }
            }
        else:
            knn_filter = {"term": {"is_active": True}}

        body: dict[str, Any] = {
            "knn": {
                "field":          "job_embedding",
                "query_vector":   user_embedding,
                "k":              k,
                "num_candidates": min(k * 5, 1000),
                "filter":         knn_filter,
            },
            "_source": ["job_id"],
            "size": k,
        }

        try:
            response = await self.client.search(index=INDEX_NAME, body=body)
            return [hit["_source"]["job_id"] for hit in response["hits"]["hits"]]
        except Exception as exc:
            logger.error("Elasticsearch kNN search failed: %s", exc)
            return []


elasticsearch_service = ElasticsearchService()
