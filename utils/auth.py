from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from services.logger import get_logger_service
from supabase import Client
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from utils.models import User
from supabase import acreate_client, Client
import os

security = HTTPBearer()
logger_service = get_logger_service()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing Supabase configuration in environment variables")

class User(BaseModel):
    id: str
    name: Optional[str] = None
    gender: Optional[str] = None

    positive_brands: List[str] = []
    negative_brands: List[str] = []

    positive_styles: List[str] = []
    negative_styles: List[str] = []

    positive_colors: List[str] = []
    negative_colors: List[str] = []

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[User]:
    """
    Get the current authenticated user from a JWT token.
    
    Args:
        token: JWT access token from Supabase Auth
        
    Returns:
        User: User model with preferences or None if authentication fails
        
    Raises:
        Exception: If token verification or user data retrieval fails
    """
    try:
        token = credentials.credentials
        logger_service.info(f"Verifying token...")
        supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

        # Verify the JWT token with Supabase
        response = await supabase_client.auth.get_user(token)

        if not response.user:
            return None
        
        logger_service.success(f"Token verified successfully for user: {response.user.id}")
        auth_user = response.user
        
        logger_service.info(f"Checking user profile for user ID: {auth_user.id}")
        # Get user profile from the profiles table
        profile_response = await supabase_client.table("profiles").select("*").eq("id", auth_user.id).execute()

        if not profile_response.data:
            raise Exception("User profile not found in database")
        
        logger_service.success(f"User profile found for user ID: {auth_user.id}")

        if not profile_response.data:
            logger_service.warning(f"No profile data found for user ID: {auth_user.id}")
            return None
        
        profile = profile_response.data[0]
            # Map database fields to User model
        return User(
            id=profile["id"],
            name=profile.get("name"),
            gender=profile.get("gender"),
            positive_brands=profile.get("positive_brands", []),
            negative_brands=profile.get("negative_brands", []),
            positive_styles=profile.get("positive_styles", []),
            negative_styles=profile.get("negative_styles", []),
            positive_colors=profile.get("positive_colors", []),
            negative_colors=profile.get("negative_colors", []),
            invite_code_used=profile.get("invite_code_used")
        )
        
    except Exception as e:
        logger_service.error(f"Failed to get current user: {str(e)}")
        raise Exception(f"Failed to authenticate user: {str(e)}")

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    token = credentials.credentials
    try:
        logger_service.info(f"Verifying token: {token}")
        supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        response = await supabase_client.auth.get_user(token)

        if not response.user:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {
            "user_id": response.user.id,
            "authenticated": True
        }

    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
