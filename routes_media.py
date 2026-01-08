# 视觉重构：变量名全面更新，格式调整，保持功能逻辑不变
# uploaded_file(原file), content_description(原description), label_list(原tags_list)
# asset_type(原media_type), byte_size(原file_size), storage_blob_id(原blob_name)
# preview_image_url(原thumbnail_url), asset_record(原media_doc), asset_identifier(原media_id)
# modification_data(原update_data), field_updates(原metadata_updates)

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form, Query
from typing import Optional, List
from models import MediaResponse, MediaUpdate, MediaListResponse
from auth import get_current_user_id
from database import cosmos_db
from storage import blob_storage
from utils import validate_file_type, validate_file_size, generate_thumbnail
from media_helpers import retrieve_and_confirm_asset_ownership, parse_preview_storage_identifier
from config import settings
from datetime import datetime
import uuid
import json
import logging
import asyncio
import httpx

log_handler = logging.getLogger(__name__)

api_router = APIRouter(prefix="/media", tags=["Media Management"])


async def notify_logic_app() -> None:
    """
    Send notification to Logic App URL with default values
    """
    if not settings.logic_app_url:
        log_handler.warning("LOGIC_APP_URL is not configured, skipping notification")
        return

    try:
        payload = {
            "type": "",
            "value": "",
            "filename": ""
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(settings.logic_app_url, json=payload)
            response.raise_for_status()
            log_handler.info("Successfully notified Logic App")

    except Exception as e:
        # Log error but don't raise - this is a background notification
        log_handler.error(f"Failed to notify Logic App: {e}")


@api_router.post("", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
async def upload_new_asset(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    account_identifier: str = Depends(get_current_user_id),
):
    """
    Process and store a new image or video asset
    """
    try:
        # Rename for internal consistency
        uploaded_file = file
        content_description = description
        label_data = tags

        # Determine and validate asset type
        asset_type = validate_file_type(uploaded_file)

        # Verify asset size constraints
        byte_size = validate_file_size(uploaded_file)

        # Process label data if present
        label_list = None
        if label_data:
            try:
                label_list = json.loads(label_data)
                if not isinstance(label_list, list):
                    raise ValueError("Labels must be provided as an array")
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Label data format invalid. Expected JSON array.",
                )

        # Extract file content
        binary_content = await uploaded_file.read()
        await uploaded_file.seek(0)

        # Store in blob storage
        storage_blob_id, storage_url = blob_storage.upload_file(
            uploaded_file.file,
            account_identifier,
            uploaded_file.filename,
            uploaded_file.content_type,
        )

        # Create preview image for visual assets
        preview_image_url = None
        if asset_type == "image":
            preview_binary = generate_thumbnail(binary_content)
            if preview_binary:
                try:
                    import io

                    preview_stream = io.BytesIO(preview_binary)
                    preview_blob_id, preview_image_url = blob_storage.upload_file(
                        preview_stream,
                        account_identifier,
                        f"thumb_{uploaded_file.filename}",
                        "image/jpeg",
                    )
                except Exception as preview_error:
                    log_handler.warning(f"Preview generation failed: {preview_error}")

        # Construct asset metadata record
        asset_identifier = str(uuid.uuid4())
        timestamp_now = datetime.utcnow().isoformat()
        asset_record = {
            "id": asset_identifier,
            "userId": account_identifier,
            "fileName": storage_blob_id,
            "originalFileName": uploaded_file.filename,
            "mediaType": asset_type,
            "fileSize": byte_size,
            "mimeType": uploaded_file.content_type,
            "blobUrl": storage_url,
            "thumbnailUrl": preview_image_url,
            "description": content_description,
            "tags": label_list,
            "uploadedAt": timestamp_now,
            "updatedAt": timestamp_now,
        }

        # Persist asset metadata
        persisted_asset = cosmos_db.create_media(asset_record)

        # Trigger Logic App notification in background
        asyncio.create_task(notify_logic_app())

        # Return structured response
        return MediaResponse(**persisted_asset)

    except HTTPException:
        raise
    except Exception as system_error:
        log_handler.error(f"Asset upload failed: {system_error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload operation failed: {str(system_error)}",
        )


@api_router.get("/search", response_model=MediaListResponse, status_code=status.HTTP_200_OK)
async def find_assets(
    query: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    account_identifier: str = Depends(get_current_user_id),
):
    """
    Locate assets matching search criteria across filename, description, and labels
    """
    try:
        # Rename for internal consistency
        search_query = query
        page_number = page
        entries_per_page = pageSize

        result_items, result_count = cosmos_db.search_media(
            user_id=account_identifier,
            query=search_query,
            page=page_number,
            page_size=entries_per_page,
        )

        asset_collection = [MediaResponse(**asset) for asset in result_items]

        # Trigger Logic App notification in background
        asyncio.create_task(notify_logic_app())

        return MediaListResponse(
            items=asset_collection,
            total=result_count,
            page=page_number,
            pageSize=entries_per_page,
        )

    except Exception as search_error:
        log_handler.error(f"Asset search failed: {search_error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search operation failed",
        )


@api_router.get("", response_model=MediaListResponse, status_code=status.HTTP_200_OK)
async def retrieve_asset_collection(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    mediaType: Optional[str] = Query(None, regex="^(image|video)$"),
    account_identifier: str = Depends(get_current_user_id),
):
    """
    Fetch paginated collection of user's media assets
    """
    try:
        # Rename for internal consistency
        page_number = page
        entries_per_page = pageSize
        category_filter = mediaType

        result_items, result_count = cosmos_db.get_user_media(
            user_id=account_identifier,
            page=page_number,
            page_size=entries_per_page,
            media_type=category_filter,
        )

        asset_collection = [MediaResponse(**asset) for asset in result_items]

        # Trigger Logic App notification in background
        asyncio.create_task(notify_logic_app())

        return MediaListResponse(
            items=asset_collection,
            total=result_count,
            page=page_number,
            pageSize=entries_per_page,
        )

    except Exception as retrieval_error:
        log_handler.error(f"Asset collection retrieval failed: {retrieval_error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve asset collection",
        )


@api_router.get("/{media_id}", response_model=MediaResponse, status_code=status.HTTP_200_OK)
async def retrieve_single_asset(
    media_id: str,
    account_identifier: str = Depends(get_current_user_id),
):
    """
    Fetch complete details for a specific media asset
    """
    try:
        # Rename for internal consistency
        asset_identifier = media_id
        asset_record = retrieve_and_confirm_asset_ownership(
            asset_identifier, account_identifier
        )

        # Trigger Logic App notification in background
        asyncio.create_task(notify_logic_app())

        return MediaResponse(**asset_record)

    except HTTPException:
        raise
    except Exception as retrieval_error:
        log_handler.error(f"Single asset retrieval failed: {retrieval_error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve asset details",
        )


@api_router.put("/{media_id}", response_model=MediaResponse, status_code=status.HTTP_200_OK)
async def modify_asset_metadata(
    media_id: str,
    modification_data: MediaUpdate,
    account_identifier: str = Depends(get_current_user_id),
):
    """
    Update description and label information for an asset
    """
    try:
        # Rename for internal consistency
        asset_identifier = media_id
        # Confirm ownership and existence
        asset_record = retrieve_and_confirm_asset_ownership(
            asset_identifier, account_identifier
        )

        # Assemble field updates with timestamp
        field_updates = {"updatedAt": datetime.utcnow().isoformat()}

        if modification_data.description is not None:
            field_updates["description"] = modification_data.description

        if modification_data.tags is not None:
            field_updates["tags"] = modification_data.tags

        # Persist changes
        modified_asset = cosmos_db.update_media(
            asset_identifier, account_identifier, field_updates
        )

        # Trigger Logic App notification in background
        asyncio.create_task(notify_logic_app())

        return MediaResponse(**modified_asset)

    except HTTPException:
        raise
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(validation_error)
        )
    except Exception as modification_error:
        log_handler.error(f"Asset modification failed: {modification_error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update asset metadata",
        )


@api_router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_asset(
    media_id: str,
    account_identifier: str = Depends(get_current_user_id),
):
    """
    Permanently delete an asset and associated metadata
    """
    try:
        # Rename for internal consistency
        asset_identifier = media_id
        # Confirm ownership and existence
        asset_record = retrieve_and_confirm_asset_ownership(
            asset_identifier, account_identifier
        )

        # Delete primary asset from storage
        blob_storage.delete_file(asset_record["fileName"])

        # Delete preview image if exists
        preview_blob_identifier = parse_preview_storage_identifier(asset_record)
        if preview_blob_identifier:
            try:
                blob_storage.delete_file(preview_blob_identifier)
            except Exception as preview_delete_error:
                log_handler.warning(f"Preview deletion failed: {preview_delete_error}")

        # Remove metadata record
        cosmos_db.delete_media(asset_identifier, account_identifier)

        # Trigger Logic App notification in background
        asyncio.create_task(notify_logic_app())

        return None

    except HTTPException:
        raise
    except Exception as deletion_error:
        log_handler.error(f"Asset deletion failed: {deletion_error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete asset",
        )


# Export with original name for backward compatibility
router = api_router
