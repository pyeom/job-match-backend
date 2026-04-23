from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    retry_after: int | None = None
