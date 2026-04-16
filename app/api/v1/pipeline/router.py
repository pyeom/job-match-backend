from fastapi import APIRouter

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# GET    /companies/{id}/pipeline-templates
# POST   /companies/{id}/pipeline-templates
# PUT    /pipeline-templates/{id}
# DELETE /pipeline-templates/{id}
# GET    /jobs/{id}/candidates              — ranked list
# PUT    /applications/{id}/stage          — move in pipeline
# POST   /applications/bulk-action         — {action, ids, stage?}
