"""
Pydantic schemas for push token operations.
"""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class PushTokenCreate(BaseModel):
    """Schema for creating/registering a push token."""
    token: str = Field(..., min_length=1, max_length=255, description="Expo push token")
    platform: str = Field(..., description="Platform (ios, android, web)")
    device_name: Optional[str] = Field(None, max_length=255, description="Device name (optional)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
                "platform": "ios",
                "device_name": "John's iPhone"
            }
        }
    }


class PushTokenResponse(BaseModel):
    """Schema for push token response."""
    id: UUID
    user_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    token: str
    platform: str
    device_name: Optional[str] = None
    is_active: bool
    last_used_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "550e8400-e29b-41d4-a716-446655440001",
                "company_id": None,
                "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
                "platform": "ios",
                "device_name": "John's iPhone",
                "is_active": True,
                "last_used_at": "2025-11-08T20:00:00Z",
                "created_at": "2025-11-08T19:00:00Z",
                "updated_at": "2025-11-08T20:00:00Z"
            }
        }
    }


class PushTokenDeleteResponse(BaseModel):
    """Schema for push token deletion response."""
    success: bool
    message: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Push token deleted successfully"
            }
        }
    }
