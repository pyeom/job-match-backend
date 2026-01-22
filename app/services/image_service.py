"""
Image processing service for avatar uploads.
Handles image resizing, format conversion, and validation.
"""
from PIL import Image
from io import BytesIO
from typing import Tuple, Optional
from fastapi import UploadFile, HTTPException
import uuid


class ImageService:
    """Service for processing and validating uploaded images."""

    # Allowed file types
    ALLOWED_MIME_TYPES = {
        "image/jpeg",
        "image/png",
        "image/webp"
    }

    # File extensions mapping
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

    # Size constraints
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB in bytes
    THUMBNAIL_SIZE = (256, 256)
    STANDARD_SIZE = (512, 512)

    # Image quality
    WEBP_QUALITY = 85

    async def validate_image(self, file: UploadFile) -> None:
        """
        Validate uploaded image file.

        Args:
            file: The uploaded file

        Raises:
            HTTPException: If validation fails
        """
        # Check content type
        if file.content_type not in self.ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: JPEG, PNG, WebP"
            )

        # Check file extension
        if file.filename:
            extension = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
            if f".{extension}" not in self.ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid file extension. Allowed: {', '.join(self.ALLOWED_EXTENSIONS)}"
                )

        # Read file content to check size
        content = await file.read()
        if len(content) > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {self.MAX_FILE_SIZE / (1024 * 1024)}MB"
            )

        # Seek back to beginning for later processing
        await file.seek(0)

        # Try to open image to validate it's a valid image file
        try:
            image = Image.open(BytesIO(content))
            image.verify()  # Verify it's a valid image
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image file: {str(e)}"
            )

        # Seek back to beginning again
        await file.seek(0)

    async def process_avatar(
        self,
        file: UploadFile
    ) -> Tuple[bytes, bytes]:
        """
        Process avatar image: resize to standard and thumbnail sizes, convert to WebP.

        Args:
            file: The uploaded image file

        Returns:
            Tuple of (standard_image_bytes, thumbnail_image_bytes)

        Raises:
            HTTPException: If processing fails
        """
        try:
            # Read file content
            content = await file.read()

            # Open image
            image = Image.open(BytesIO(content))

            # Convert to RGB if necessary (for PNG with transparency, RGBA, etc.)
            if image.mode in ('RGBA', 'LA', 'P'):
                # Create a white background
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')

            # Create standard size image
            standard_image = self._resize_image(image, self.STANDARD_SIZE)
            standard_bytes = self._convert_to_webp(standard_image)

            # Create thumbnail
            thumbnail_image = self._resize_image(image, self.THUMBNAIL_SIZE)
            thumbnail_bytes = self._convert_to_webp(thumbnail_image)

            return standard_bytes, thumbnail_bytes

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error processing image: {str(e)}"
            )

    def _resize_image(self, image: Image.Image, size: Tuple[int, int]) -> Image.Image:
        """
        Resize image to specified dimensions while maintaining aspect ratio.

        Args:
            image: PIL Image object
            size: Target size (width, height)

        Returns:
            Resized PIL Image object
        """
        # Create a copy to avoid modifying the original
        img_copy = image.copy()

        # Calculate aspect ratio
        aspect_ratio = img_copy.width / img_copy.height
        target_aspect = size[0] / size[1]

        if aspect_ratio > target_aspect:
            # Image is wider than target - crop width
            new_width = int(img_copy.height * target_aspect)
            left = (img_copy.width - new_width) // 2
            img_copy = img_copy.crop((left, 0, left + new_width, img_copy.height))
        elif aspect_ratio < target_aspect:
            # Image is taller than target - crop height
            new_height = int(img_copy.width / target_aspect)
            top = (img_copy.height - new_height) // 2
            img_copy = img_copy.crop((0, top, img_copy.width, top + new_height))

        # Resize to target dimensions using high-quality resampling
        resized = img_copy.resize(size, Image.Resampling.LANCZOS)
        return resized

    def _convert_to_webp(self, image: Image.Image) -> bytes:
        """
        Convert image to WebP format.

        Args:
            image: PIL Image object

        Returns:
            Image bytes in WebP format
        """
        output = BytesIO()
        image.save(
            output,
            format='WEBP',
            quality=self.WEBP_QUALITY,
            method=6  # Best compression
        )
        return output.getvalue()

    def validate_file_size(self, content_length: Optional[int]) -> None:
        """
        Validate file size from Content-Length header.

        Args:
            content_length: Content-Length value from request header

        Raises:
            HTTPException: If file is too large
        """
        if content_length and content_length > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {self.MAX_FILE_SIZE / (1024 * 1024)}MB"
            )


# Singleton instance
image_service = ImageService()
