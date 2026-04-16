"""Integration test: verify MALA tables were created by migration."""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — skipping DB integration tests"
)

EXPECTED_TABLES = [
    "candidate_puc_profiles",
    "candidate_mala_responses",
    "company_org_profiles",
    "job_match_configs",
    "match_scores",
    "hiring_outcomes",
]

@pytest.mark.asyncio
async def test_mala_tables_exist():
    import asyncpg
    url = os.getenv("TEST_DATABASE_URL")
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        existing = {r["tablename"] for r in rows}
        for table in EXPECTED_TABLES:
            assert table in existing, f"Table {table!r} missing from DB"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_puc_vector_index_exists():
    import asyncpg
    url = os.getenv("TEST_DATABASE_URL")
    conn = await asyncpg.connect(url)
    try:
        row = await conn.fetchrow(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'candidate_puc_profiles' AND indexname = 'idx_puc_vector'"
        )
        assert row is not None, "ivfflat index idx_puc_vector missing"
    finally:
        await conn.close()
