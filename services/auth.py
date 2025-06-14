from fastapi import HTTPException, status
from fastapi.security import HTTPBearer
from supabase import create_client, Client
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import os
from datetime import datetime
from pydantic import BaseModel
from typing import List

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
        self.guest_request_limit = 3  # Maximum requests per guest

    def verify_token(self, token: str) -> User:
        """
        Verify JWT token and return user data.
        
        Args:
            token: JWT token to verify
            
        Returns:
            User: User model instance with profile data
            
        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            # Use Supabase to verify the token
            response = self.anon_client.auth.get_user(token)
            if response.user:
                # Get additional user profile data from the profiles table
                profile_response = self.supabase.table("profiles").select("*").eq("id", response.user.id).execute()
                
                # Extract user metadata for User model
                user_metadata = response.user.user_metadata or {}
                profile_data = profile_response.data[0] if profile_response.data else {}
                
                # Create User model instance
                user = User(
                    id=response.user.id,
                    name=user_metadata.get("name") or profile_data.get("full_name"),
                    gender=user_metadata.get("gender") or profile_data.get("gender"),
                    positive_brands=profile_data.get("positive_brands", []),
                    negative_brands=profile_data.get("negative_brands", []),
                    positive_styles=profile_data.get("positive_styles", []),
                    negative_styles=profile_data.get("negative_styles", []),
                    positive_colors=profile_data.get("positive_colors", []),
                    negative_colors=profile_data.get("negative_colors", [])
                )
                return user
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token"
                )
        except Exception as e:
            print(f"Token verification error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get user data by user ID.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            User: User model instance or None if user not found
        """
        try:
            response = self.supabase.auth.admin.get_user_by_id(user_id)
            if response.user:
                # Get additional user profile data from the profiles table
                profile_response = self.supabase.table("profiles").select("*").eq("id", user_id).execute()
                
                # Extract user metadata for User model
                user_metadata = response.user.user_metadata or {}
                profile_data = profile_response.data[0] if profile_response.data else {}
                
                # Create User model instance
                user = User(
                    id=response.user.id,
                    name=user_metadata.get("name") or profile_data.get("full_name"),
                    gender=user_metadata.get("gender") or profile_data.get("gender"),
                    positive_brands=profile_data.get("positive_brands", []),
                    negative_brands=profile_data.get("negative_brands", []),
                    positive_styles=profile_data.get("positive_styles", []),
                    negative_styles=profile_data.get("negative_styles", []),
                    positive_colors=profile_data.get("positive_colors", []),
                    negative_colors=profile_data.get("negative_colors", [])
                )
                return user
            return None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None

    def create_user_profile(self, user_id: str, email: str, metadata: Dict[str, Any] = None) -> Optional[User]:
        """
        Create or update user profile in the profiles table.
        
        Args:
            user_id: The user's unique identifier
            email: User's email address
            metadata: Additional user metadata (optional)
            
        Returns:
            User: User model instance or None if failed
        """
        try:
            profile_data = {
                "id": user_id,
                "email": email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "positive_brands": [],
                "negative_brands": [],
                "positive_styles": [],
                "negative_styles": [],
                "positive_colors": [],
                "negative_colors": []
            }
            
            if metadata:
                profile_data.update({
                    "full_name": metadata.get("full_name"),
                    "avatar_url": metadata.get("avatar_url"),
                    "provider": metadata.get("provider"),
                    "gender": metadata.get("gender")
                })

            # Upsert user profile
            response = self.supabase.table("profiles").upsert(profile_data).execute()
            
            if response.data:
                created_profile = response.data[0]
                # Create User model instance from the created profile
                user = User(
                    id=created_profile["id"],
                    name=created_profile.get("full_name"),
                    gender=created_profile.get("gender"),
                    positive_brands=created_profile.get("positive_brands", []),
                    negative_brands=created_profile.get("negative_brands", []),
                    positive_styles=created_profile.get("positive_styles", []),
                    negative_styles=created_profile.get("negative_styles", []),
                    positive_colors=created_profile.get("positive_colors", []),
                    negative_colors=created_profile.get("negative_colors", [])
                )
                return user
            return None
        except Exception as e:
            print(f"Error creating user profile: {e}")
            return None