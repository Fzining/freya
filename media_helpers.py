"""
Helper utilities for media route operations
Contains shared validation and verification functions
"""

# 视觉重构：函数名和变量名全面更新，保持功能逻辑不变
# retrieve_and_confirm_asset_ownership(原fetch_and_verify_media_ownership)
# confirm_asset_presence(原validate_media_existence)
# parse_preview_storage_identifier(原extract_thumbnail_blob_identifier)

from fastapi import HTTPException, status
from database import cosmos_db
import logging

log_handler = logging.getLogger(__name__)


def retrieve_and_confirm_asset_ownership(asset_identifier: str, account_identifier: str) -> dict:
    """
    Retrieve asset record and confirm ownership rights

    Args:
        asset_identifier: Unique identifier for the asset
        account_identifier: Unique identifier for the requesting account

    Returns:
        dict: Asset document if located and owned by specified account

    Raises:
        HTTPException: When asset is unavailable or ownership is invalid
    """
    asset_document = cosmos_db.get_media_by_id(asset_identifier, account_identifier)

    if not asset_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset resource could not be located"
        )

    if asset_document["userId"] != account_identifier:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization failed: insufficient rights to access this asset"
        )

    return asset_document


def confirm_asset_presence(asset_identifier: str, account_identifier: str) -> dict:
    """
    Verify asset existence and retrieve record (ownership pre-verified)
    Useful when authorization has been validated at a higher layer

    Args:
        asset_identifier: Unique identifier for the asset
        account_identifier: Unique identifier for the account

    Returns:
        dict: Asset document if present

    Raises:
        HTTPException: When asset cannot be found
    """
    asset_document = cosmos_db.get_media_by_id(asset_identifier, account_identifier)

    if not asset_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Specified asset resource is not available"
        )

    return asset_document


def parse_preview_storage_identifier(asset_document: dict) -> str | None:
    """
    Extract preview image storage identifier from asset record

    Args:
        asset_document: Complete asset metadata record

    Returns:
        str | None: Preview storage identifier or None if unavailable
    """
    if not asset_document.get("thumbnailUrl"):
        return None

    try:
        source_filename = asset_document["originalFileName"].split("/")[-1]
        preview_storage_id = asset_document["fileName"].replace(
            source_filename,
            f"thumb_{source_filename}"
        )
        return preview_storage_id
    except Exception as parse_error:
        log_handler.warning(f"Preview identifier extraction failed: {parse_error}")
        return None
