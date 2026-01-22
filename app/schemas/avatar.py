"""
Pydantic schemas for avatar upload endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional


class AvatarUploadResponse(BaseModel):
    """Response schema for avatar upload endpoint."""

    avatar_url: str = Field(..., description="URL to the standard size avatar (512x512)")
    avatar_thumbnail_url: str = Field(..., description="URL to the thumbnail avatar (256x256)")
    message: str = Field(default="Avatar uploaded successfully")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "avatar_url": "/api/v1/media/avatars/123e4567-e89b-12d3-a456-426614174000/abc123_standard.webp",
                "avatar_thumbnail_url": "/api/v1/media/avatars/123e4567-e89b-12d3-a456-426614174000/def456_thumbnail.webp",
                "message": "Avatar uploaded successfully"
            }
        }


class AvatarDeleteResponse(BaseModel):
    """Response schema for avatar deletion endpoint."""

    message: str = Field(default="Avatar deleted successfully")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Avatar deleted successfully"
            }
        }


class RateLimitError(BaseModel):
    """Response schema for rate limit errors."""

    detail: str = Field(..., description="Error message")
    retry_after: int = Field(..., description="Seconds until rate limit resets")

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Rate limit exceeded. Maximum 10 uploads per hour.",
                "retry_after": 3420
            }
        }
