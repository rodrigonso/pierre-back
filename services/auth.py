from fastapi import HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import os
from datetime import datetime
from pydantic import BaseModel
from typing import List
from utils.models import User
from services.logger import get_logger_service

logger_service = get_logger_service()

# Load environment variables
load_dotenv()

# Supabase client setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY]):
    raise ValueError("Missing Supabase configuration in environment variables")

# Create Supabase clients
supabase_service: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
supabase_anon: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Security scheme
security = HTTPBearer()

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

class AuthService:
    """
    Authentication service for handling user operations, token verification using Supabase as the backend.
    """
    
    def __init__(self):
        """Initialize the AuthService with Supabase clients and configuration."""
        self.supabase = supabase_service
        self.anon_client = supabase_anon

    async def get_current_user(self, token: str) -> Optional[User]:
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

            print(f"Verifying token: {token}")
            logger_service.info(f"Verifying token...")

            # Verify the JWT token with Supabase
            response = self.supabase.auth.get_user(token)
            
            if not response.user:
                return None
            
            logger_service.success(f"Token verified successfully for user: {response.user.id}")
            auth_user = response.user
            
            logger_service.info(f"Checking user profile for user ID: {auth_user.id}")
            # Get user profile from the profiles table
            profile_response = self.supabase.table("profiles").select("*").eq("id", auth_user.id).execute()
            
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
                negative_colors=profile.get("negative_colors", [])
            )
            
        except Exception as e:
            logger_service.error(f"Failed to get current user: {str(e)}")
            raise Exception(f"Failed to authenticate user: {str(e)}")

    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify a JWT token and return user information.
        
        Args:
            token: JWT access token
            
        Returns:
            Dict containing user information
            
        Raises:
            HTTPException: If token is invalid
        """
        try:
            response = self.supabase.auth.get_user(token)
            
            if not response.user:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            return {
                "user_id": response.user.id,
                "email": response.user.email,
                "authenticated": True
            }
            
        except Exception as e:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get user data by user ID.
        
        Args:
            user_id: User's unique identifier
            
        Returns:
            User model containing user data or None if not found
        """
        try:
            response = self.supabase.table("profiles").select("*").eq("id", user_id).execute()
            
            if response.data:
                profile = response.data[0]
                return User(
                    id=profile["id"],
                    name=profile.get("name"),
                    gender=profile.get("gender"),
                    positive_brands=profile.get("positive_brands", []),
                    negative_brands=profile.get("negative_brands", []),
                    positive_styles=profile.get("positive_styles", []),
                    negative_styles=profile.get("negative_styles", []),
                    positive_colors=profile.get("positive_colors", []),
                    negative_colors=profile.get("negative_colors", [])
                )

            return None
            
        except Exception as e:
            print(f"Error getting user by ID: {e}")
            return None

auth_service = AuthService()
def get_auth_service() -> AuthService:
    """
    Dependency to get the authentication service instance.
    
    Returns:
        AuthService: Instance of the authentication service
    """
    return auth_service