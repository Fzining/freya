# 视觉重构：变量名全面更新，格式调整，保持功能逻辑不变
# account_info(原user_data), credentials(原login_data), current_account(原existing_user)
# account_record(原user_doc), jwt_token(原access_token)

from fastapi import APIRouter, HTTPException, status, Depends
from models import UserCreate, LoginRequest, Token, UserResponse
from auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user_id,
)
from database import cosmos_db
from datetime import datetime
import uuid
import logging

log_handler = logging.getLogger(__name__)

api_router = APIRouter(prefix="/auth", tags=["Authentication"])


@api_router.post("/register", response_model=Token, status_code=status.HTTP_200_OK)
async def register_new_account(account_info: UserCreate):
    """
    Create a new user account with provided credentials
    """
    try:
        # Verify account doesn't already exist
        log_handler.info(f"Account creation requested for: {account_info.email}")
        current_account = cosmos_db.get_user_by_email(account_info.email)
        if current_account:
            log_handler.warning(
                f"Account creation denied: Email exists - {account_info.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists",
            )

        # Construct new account record
        generated_account_id = str(uuid.uuid4())
        account_record = {
            "id": generated_account_id,
            "username": account_info.username,
            "email": account_info.email,
            "hashed_password": get_password_hash(account_info.password),
            "created_at": datetime.utcnow().isoformat(),
        }

        # Persist to database
        persisted_account = cosmos_db.create_user(account_record)
        log_handler.info(f"Account successfully created: {account_info.email}")

        # Generate authentication token
        jwt_token = create_access_token(
            data={"sub": generated_account_id, "email": account_info.email}
        )

        # Build response payload
        account_response_data = UserResponse(
            id=persisted_account["id"],
            username=persisted_account["username"],
            email=persisted_account["email"],
            createdAt=persisted_account["created_at"],
        )

        return Token(token=jwt_token, user=account_response_data)

    except HTTPException:
        raise
    except ValueError as validation_error:
        log_handler.error(f"Account validation failed: {validation_error}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(validation_error)
        )
    except Exception as system_error:
        log_handler.error(f"Account creation system error: {system_error}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Account creation failed: {str(system_error)}",
        )


@api_router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
async def authenticate_account(credentials: LoginRequest):
    """
    Verify credentials and issue authentication token
    """
    try:
        # Retrieve account by email
        log_handler.info(f"Authentication requested for: {credentials.email}")
        account_record = cosmos_db.get_user_by_email(credentials.email)
        if not account_record:
            log_handler.warning(
                f"Authentication failed: Account not found - {credentials.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email or password is incorrect",
            )

        # Validate password
        password_valid = verify_password(
            credentials.password, account_record["hashed_password"]
        )
        if not password_valid:
            log_handler.warning(
                f"Authentication failed: Password mismatch - {credentials.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email or password is incorrect",
            )

        # Issue JWT authentication token
        jwt_token = create_access_token(
            data={
                "sub": account_record["id"],
                "email": account_record["email"]
            }
        )

        # Construct response
        account_response_data = UserResponse(
            id=account_record["id"],
            username=account_record["username"],
            email=account_record["email"],
            createdAt=account_record["created_at"],
        )

        log_handler.info(f"Authentication successful: {account_record['email']}")
        return Token(token=jwt_token, user=account_response_data)

    except HTTPException:
        raise
    except Exception as system_error:
        log_handler.error(f"Authentication system error: {system_error}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(system_error)}",
        )


# Export with original name for backward compatibility
router = api_router
