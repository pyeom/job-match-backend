from fastapi import APIRouter
from app.api.v1.users.endpoints import router as user_router
from app.api.v1.users.push_tokens import router as push_tokens_router

# Create a single router that combines all user endpoints
router = APIRouter()

# Include all sub-routers
router.include_router(user_router)
router.include_router(push_tokens_router)

__all__ = ["router"]
