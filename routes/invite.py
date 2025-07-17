from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from services.db import get_database_service
from utils.auth import get_current_user, verify_token
from utils.models import User
from services.logger import get_logger_service
import uuid

router = APIRouter()
logger_service = get_logger_service()
security = HTTPBearer()

# Pydantic Models for Invite Codes
class InviteCodeCreate(BaseModel):
    """
    Model for creating a new invite code
    
    Attributes:
        code: Optional custom code (if not provided, will be auto-generated)
        description: Optional description for the invite code
        max_uses: Maximum number of times the code can be used (default: 1)
        expires_at: Optional expiration datetime
    """
    code: Optional[str] = None
    description: Optional[str] = None
    max_uses: int = Field(default=1, ge=1, description="Maximum uses must be at least 1")
    expires_at: Optional[datetime] = None

class InviteCodeValidation(BaseModel):
    """
    Model for validating an invite code
    
    Attributes:
        code: The invite code to validate
    """
    code: str = Field(..., min_length=1, max_length=50, description="Invite code to validate")

class InviteCodeResponse(BaseModel):
    """
    Response model for invite code operations
    
    Attributes:
        id: Unique identifier for the invite code
        code: The invite code string
        description: Description of the invite code
        max_uses: Maximum number of times the code can be used
        current_uses: Current number of times the code has been used
        is_active: Whether the code is currently active
        expires_at: Optional expiration datetime
        created_at: When the code was created
        created_by: User ID who created the code
    """
    id: str
    code: str
    description: Optional[str] = None
    max_uses: int
    current_uses: int
    is_active: bool
    expires_at: Optional[datetime] = None
    created_at: datetime
    created_by: Optional[str] = None

class InviteCodeValidationResponse(BaseModel):
    """
    Response model for invite code validation
    
    Attributes:
        valid: Whether the invite code is valid and can be used
        message: Descriptive message about the validation result
        code: The validated invite code (echo back for confirmation)
    """
    valid: bool
    message: str
    code: str

@router.post("/invite/validate", response_model=InviteCodeValidationResponse)
async def validate_invite_code(request: InviteCodeValidation):
    """
    Validate an invite code without consuming it.
    
    This endpoint checks if an invite code is valid, active, not expired,
    and has remaining uses. It does NOT consume the invite code.
    
    Args:
        request: InviteCodeValidation containing the code to validate
        
    Returns:
        InviteCodeValidationResponse: Validation result with status and message
        
    Raises:
        HTTPException: For any database or validation errors
    """
    try:
        logger_service.info(f"Validating invite code: {request.code}")

        db_service = await get_database_service()
        supabase = db_service.supabase

        # Query the invite code
        response = await supabase.table("invite_codes").select("*").eq("code", request.code).execute()
        
        if not response.data:
            logger_service.warning(f"Invite code not found: {request.code}")
            return InviteCodeValidationResponse(
                valid=False,
                message="Invite code not found",
                code=request.code
            )
        
        invite_code = response.data[0]
        
        # Check if code is active
        if not invite_code["is_active"]:
            logger_service.warning(f"Invite code is inactive: {request.code}")
            return InviteCodeValidationResponse(
                valid=False,
                message="Invite code is not active",
                code=request.code
            )
        
        # Check if code has expired
        if invite_code["expires_at"]:
            expires_at = datetime.fromisoformat(invite_code["expires_at"].replace('Z', '+00:00'))
            if expires_at <= datetime.now(expires_at.tzinfo):
                logger_service.warning(f"Invite code has expired: {request.code}")
                return InviteCodeValidationResponse(
                    valid=False,
                    message="Invite code has expired",
                    code=request.code
                )
        
        # Check if code has remaining uses
        if invite_code["current_uses"] >= invite_code["max_uses"]:
            logger_service.warning(f"Invite code has no remaining uses: {request.code}")
            return InviteCodeValidationResponse(
                valid=False,
                message="Invite code has been fully used",
                code=request.code
            )
        
        remaining_uses = invite_code["max_uses"] - invite_code["current_uses"]
        logger_service.success(f"Invite code is valid: {request.code} ({remaining_uses} uses remaining)")
        
        return InviteCodeValidationResponse(
            valid=True,
            message=f"Invite code is valid ({remaining_uses} uses remaining)",
            code=request.code
        )
        
    except Exception as e:
        logger_service.error(f"Error validating invite code {request.code}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to validate invite code: {str(e)}")

@router.post("/invite/use", response_model=InviteCodeValidationResponse)
async def use_invite_code(request: InviteCodeValidation):
    """
    Use (consume) an invite code.
    
    This endpoint validates and consumes an invite code, incrementing its usage count.
    This should be called during user registration/onboarding process.
    
    Args:
        request: InviteCodeValidation containing the code to use
        
    Returns:
        InviteCodeValidationResponse: Result of using the invite code
        
    Raises:
        HTTPException: For any database or validation errors
    """
    try:
        logger_service.info(f"Attempting to use invite code: {request.code}")

        db_service = await get_database_service()
        supabase = db_service.supabase
        
        # Use the database function to atomically validate and consume the code
        response = await supabase.rpc("use_invite_code", {"code_to_use": request.code}).execute()
        
        if not response.data:
            logger_service.warning(f"Failed to use invite code: {request.code}")
            return InviteCodeValidationResponse(
                valid=False,
                message="Invalid or unusable invite code",
                code=request.code
            )
        
        # response.data should be a boolean indicating success
        success = response.data
        
        if success:
            logger_service.success(f"Successfully used invite code: {request.code}")
            return InviteCodeValidationResponse(
                valid=True,
                message="Invite code successfully used",
                code=request.code
            )
        else:
            logger_service.warning(f"Invite code could not be used: {request.code}")
            return InviteCodeValidationResponse(
                valid=False,
                message="Invite code is invalid, expired, or fully used",
                code=request.code
            )
        
    except Exception as e:
        logger_service.error(f"Error using invite code {request.code}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to use invite code: {str(e)}")