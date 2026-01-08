# 视觉重构：函数名和变量名全面更新，保持功能逻辑不变
# determine_file_category(原validate_file_type), verify_file_constraints(原validate_file_size)
# create_preview_image(原generate_thumbnail), render_readable_size(原format_file_size)

from fastapi import UploadFile, HTTPException, status
from PIL import Image
import io
from typing import Optional
from config import settings
import logging

log_handler = logging.getLogger(__name__)


def determine_file_category(uploaded_file: UploadFile) -> str:
    """
    Analyze file type and determine category (image or video)
    """
    mime_type = uploaded_file.content_type.lower()

    if mime_type in settings.allowed_image_types_list:
        return "image"
    elif mime_type in settings.allowed_video_types_list:
        return "video"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content type '{mime_type}' is not permitted. Supported types: {settings.allowed_image_types}, {settings.allowed_video_types}",
        )


def verify_file_constraints(uploaded_file: UploadFile, size_limit: int = None) -> int:
    """
    Check file size against constraints and return size in bytes
    """
    if size_limit is None:
        size_limit = settings.max_file_size_bytes

    # Determine file size by seeking
    uploaded_file.file.seek(0, 2)  # Move to end
    measured_size = uploaded_file.file.tell()
    uploaded_file.file.seek(0)  # Return to beginning

    if measured_size > size_limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size ({measured_size / (1024 * 1024):.2f} MB) surpasses maximum limit ({size_limit / (1024 * 1024):.0f} MB)",
        )

    return measured_size


def create_preview_image(visual_data: bytes, dimension_limit: tuple = (300, 300)) -> Optional[bytes]:
    """
    Generate preview thumbnail from image binary data
    Returns preview as bytes or None if generation fails
    """
    try:
        # Load image from binary
        source_image = Image.open(io.BytesIO(visual_data))

        # Handle transparency modes by converting to RGB
        if source_image.mode in ("RGBA", "LA", "P"):
            white_canvas = Image.new("RGB", source_image.size, (255, 255, 255))
            if source_image.mode == "P":
                source_image = source_image.convert("RGBA")
            white_canvas.paste(
                source_image,
                mask=source_image.split()[-1] if source_image.mode == "RGBA" else None
            )
            source_image = white_canvas

        # Resize to thumbnail dimensions
        source_image.thumbnail(dimension_limit, Image.Resampling.LANCZOS)

        # Serialize to bytes
        byte_buffer = io.BytesIO()
        source_image.save(byte_buffer, format="JPEG", quality=85, optimize=True)
        byte_buffer.seek(0)

        return byte_buffer.read()

    except Exception as preview_error:
        log_handler.error(f"Preview generation failed: {preview_error}")
        return None


def render_readable_size(bytes_count: int) -> str:
    """Convert byte count to human-friendly format"""
    for size_unit in ["B", "KB", "MB", "GB"]:
        if bytes_count < 1024.0:
            return f"{bytes_count:.2f} {size_unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.2f} TB"


# Export with original names for backward compatibility
validate_file_type = determine_file_category
validate_file_size = verify_file_constraints
generate_thumbnail = create_preview_image
format_file_size = render_readable_size
