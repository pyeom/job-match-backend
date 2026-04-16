"""
HTTP client for the job-match-mala microservice.
Called from arq background workers — never in the request/response path.
"""
import httpx
from app.core.config import settings

MALA_URL = getattr(settings, "mala_service_url", "http://localhost:8001")


async def analyze_candidate(candidate_id: str, cv_text: str, answers: list[dict]) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{MALA_URL}/analyze/candidate",
            json={"candidate_id": candidate_id, "cv_text": cv_text, "mala_answers": answers},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()


async def analyze_job(job_offer_id: str, description: str, e_answers: list[dict]) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{MALA_URL}/analyze/job",
            json={"job_offer_id": job_offer_id, "description": description, "e_answers": e_answers},
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()
