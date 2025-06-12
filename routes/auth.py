from fastapi import APIRouter, HTTPException, status, Depends, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from services.auth import AuthService
from utils.models import UserProfile

# Load environment variables
load_dotenv()

# Create router for authentication endpoints
router = APIRouter()

# Security scheme
security = HTTPBearer()
auth_service = AuthService()

# Dependency for getting current user
async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> Dict[str, Any]:
    """
    Dependency to get current authenticated user.
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        Dict containing authenticated user data
        
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    return auth_service.verify_token(token)

# Authentication endpoints
@router.get("/auth/user", response_model=UserProfile)
async def get_user_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Get current user profile"""
    user_data = auth_service.get_user_by_id(current_user["user_id"])
    if not user_data:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    return UserProfile(**user_data)

@router.put("/auth/user", response_model=UserProfile)
async def update_user_profile(
    profile_data: dict,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Update user profile"""
    updated_profile = auth_service.create_user_profile(
        current_user["user_id"],
        current_user["email"],
        profile_data
    )
    
    if not updated_profile:
        raise HTTPException(status_code=400, detail="Failed to update profile")
    
    return UserProfile(**updated_profile)
