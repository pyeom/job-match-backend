"""
Media file serving endpoints.
Serves uploaded avatar images and other media files.
"""
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pathlib import Path
import uuid


router = APIRouter()


@router.get("/avatars/{user_id}/{filename}")
async def serve_avatar(user_id: uuid.UUID, filename: str):
    """
    Serve avatar image files.

    Args:
        user_id: The user's UUID
        filename: The avatar filename

    Returns:
        FileResponse with the image file

    Raises:
        HTTPException: If file not found or invalid filename
    """
    # Validate filename to prevent directory traversal attacks
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    # Construct file path
    file_path = Path("uploads") / "avatars" / str(user_id) / filename

    # Check if file exists
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

    # Serve the file
    # FastAPI will automatically set the correct Content-Type based on file extension
    return FileResponse(
        path=file_path,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
        }
    )
