from fastapi import APIRouter
from app.api.v1.users.endpoints import router as user_router
from app.api.v1.users.push_tokens import router as push_tokens_router
from app.api.v1.users.filter_presets import router as filter_presets_router
from app.api.v1.users.recent_searches import router as recent_searches_router
from app.api.v1.users.avatar import router as avatar_router
from app.api.v1.users.user_notifications import router as user_notifications_router

# Create a single router that combines all user endpoints
router = APIRouter()

# Include all sub-routers
router.include_router(user_router)
router.include_router(push_tokens_router)
router.include_router(filter_presets_router)
router.include_router(recent_searches_router)
router.include_router(avatar_router)
router.include_router(user_notifications_router)

__all__ = ["router"]
