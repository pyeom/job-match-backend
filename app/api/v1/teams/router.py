from fastapi import APIRouter

router = APIRouter(prefix="/teams", tags=["teams"])

# GET    /companies/{id}/teams
# POST   /companies/{id}/teams
# GET    /teams/{id}
# PUT    /teams/{id}
# DELETE /teams/{id}
# POST   /teams/{id}/members
# DELETE /teams/{id}/members/{userId}
# POST   /teams/{id}/jobs/{jobId}
# DELETE /teams/{id}/jobs/{jobId}
