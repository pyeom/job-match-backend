from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID


class PipelineService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_templates(self, company_id: UUID):
        raise NotImplementedError

    async def create_template(self, company_id: UUID, data):
        raise NotImplementedError

    async def move_application_stage(self, application_id: UUID, stage_order: int, stage_name: str, moved_by: UUID, notes: str | None = None):
        raise NotImplementedError

    async def bulk_action(self, application_ids: list[UUID], action: str, stage_order: int | None, stage_name: str | None, moved_by: UUID):
        raise NotImplementedError

    async def get_job_candidates_ranked(self, job_id: UUID):
        raise NotImplementedError
