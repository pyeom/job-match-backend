"""
Media file serving endpoints.
Serves uploaded avatar images and other media files.
When MEDIA_CDN_URL is configured, redirects to the CDN instead of serving locally.
"""
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, RedirectResponse
from pathlib import Path
import uuid

from app.core.config import settings


router = APIRouter()


@router.get("/avatars/{user_id}/{filename}")
async def serve_avatar(user_id: uuid.UUID, filename: str, request: Request):
    """
    Serve avatar image files.

    When MEDIA_CDN_URL is configured, issues a permanent redirect to the CDN URL.
    Otherwise serves the file directly from local storage.

    Args:
        user_id: The user's UUID
        filename: The avatar filename

    Returns:
        RedirectResponse to CDN (when configured) or FileResponse with the image file

    Raises:
        HTTPException: If file not found or invalid filename
    """
    # Validate filename to prevent directory traversal attacks
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    # When CDN is configured, redirect there instead of serving locally
    if settings.media_cdn_url:
        cdn = settings.media_cdn_url.rstrip("/")
        cdn_url = f"{cdn}/avatars/{user_id}/{filename}"
        return RedirectResponse(url=cdn_url, status_code=status.HTTP_301_MOVED_PERMANENTLY)

    # Local file serving
    file_path = Path("uploads") / "avatars" / str(user_id) / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar not found"
        )

    # Verify the file is within the expected directory (security check)
    try:
        file_path = file_path.resolve()
        base_path = (Path("uploads") / "avatars").resolve()

        if not str(file_path).startswith(str(base_path)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error accessing file"
        )

    # Compute ETag from file size + modification time
    stat = file_path.stat()
    etag = f'"{stat.st_size}-{int(stat.st_mtime)}"'

    # Handle conditional GET (If-None-Match)
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=86400"})

    return FileResponse(
        path=file_path,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=86400",
            "ETag": etag,
        }
    )
