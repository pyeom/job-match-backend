import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from app.core.database import get_db
from app.api.deps import (
    get_company_user_with_verification,
    require_company_access,
    require_company_role,
)
from app.models.user import User
from app.models.team import CompanyTeam, TeamMember, TeamJobAssignment
from app.models.job import Job

router = APIRouter()


class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = None


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = "member"


class TeamResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class TeamMemberResponse(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
    role: str

    model_config = {"from_attributes": True}


@router.get("/companies/{company_id}/teams", response_model=List[TeamResponse])
async def list_teams(
    company_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
):
    require_company_access(current_user, company_id)
    result = await db.execute(
        select(CompanyTeam).where(CompanyTeam.company_id == company_id)
    )
    return result.scalars().all()


@router.post("/companies/{company_id}/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    company_id: uuid.UUID,
    body: TeamCreate,
    current_user: User = Depends(require_company_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    require_company_access(current_user, company_id)
    team = CompanyTeam(
        id=uuid.uuid4(),
        company_id=company_id,
        name=body.name,
        description=body.description,
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


@router.get("/teams/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CompanyTeam).where(CompanyTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    require_company_access(current_user, team.company_id)
    return team


@router.put("/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: uuid.UUID,
    body: TeamUpdate,
    current_user: User = Depends(require_company_role(["admin", "recruiter"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CompanyTeam).where(CompanyTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    require_company_access(current_user, team.company_id)
    if body.name is not None:
        team.name = body.name
    if body.description is not None:
        team.description = body.description
    await db.commit()
    await db.refresh(team)
    return team


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID,
    current_user: User = Depends(require_company_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CompanyTeam).where(CompanyTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    require_company_access(current_user, team.company_id)
    await db.delete(team)
    await db.commit()


@router.post("/teams/{team_id}/members", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    team_id: uuid.UUID,
    body: TeamMemberAdd,
    current_user: User = Depends(require_company_role(["admin", "recruiter"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CompanyTeam).where(CompanyTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    require_company_access(current_user, team.company_id)

    existing = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == body.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a member of this team")

    member = TeamMember(team_id=team_id, user_id=body.user_id, role=body.role)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(require_company_role(["admin", "recruiter"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CompanyTeam).where(CompanyTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    require_company_access(current_user, team.company_id)

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await db.delete(member)
    await db.commit()


@router.post("/teams/{team_id}/jobs/{job_id}", status_code=status.HTTP_201_CREATED)
async def assign_job(
    team_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: User = Depends(require_company_role(["admin", "recruiter"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CompanyTeam).where(CompanyTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    require_company_access(current_user, team.company_id)

    job_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.company_id == team.company_id)
    )
    if not job_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found for this company")

    existing = await db.execute(
        select(TeamJobAssignment).where(
            TeamJobAssignment.team_id == team_id,
            TeamJobAssignment.job_id == job_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job already assigned to this team")

    assignment = TeamJobAssignment(team_id=team_id, job_id=job_id)
    db.add(assignment)
    await db.commit()
    return {"team_id": str(team_id), "job_id": str(job_id)}


@router.delete("/teams/{team_id}/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_job(
    team_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: User = Depends(require_company_role(["admin", "recruiter"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CompanyTeam).where(CompanyTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    require_company_access(current_user, team.company_id)

    result = await db.execute(
        select(TeamJobAssignment).where(
            TeamJobAssignment.team_id == team_id,
            TeamJobAssignment.job_id == job_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    await db.delete(assignment)
    await db.commit()
