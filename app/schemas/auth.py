from pydantic import BaseModel, EmailStr
from typing import Optional


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class LogoutResponse(BaseModel):
    message: str
    detail: Optional[str] = None