from sqlalchemy.ext.asyncio import AsyncSession


class TeamService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_company_teams(self, company_id):
        raise NotImplementedError

    async def create_team(self, company_id, data):
        raise NotImplementedError

    async def add_member(self, team_id, user_id, role):
        raise NotImplementedError

    async def remove_member(self, team_id, user_id):
        raise NotImplementedError

    async def assign_job(self, team_id, job_id):
        raise NotImplementedError
