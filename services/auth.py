from fastapi import HTTPException, status
from fastapi.security import HTTPBearer
from supabase import create_client, Client
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import os
from datetime import datetime

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

class AuthService:
    """
    Authentication service for handling user operations, token verification using Supabase as the backend.
    """
    
    def __init__(self):
        """Initialize the AuthService with Supabase clients and configuration."""
        self.supabase = supabase_service
        self.anon_client = supabase_anon
        self.guest_request_limit = 3  # Maximum requests per guest
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify JWT token and return user data.
        
        Args:
            token: JWT token to verify
            
        Returns:
            Dict containing user data (user_id, email, metadata)
            
        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            # Use Supabase to verify the token
            response = self.anon_client.auth.get_user(token)
            if response.user:
                return {
                    "user_id": response.user.id,
                    "email": response.user.email,
                    "user_metadata": response.user.user_metadata,
                    "app_metadata": response.user.app_metadata
                }
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
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user data by user ID.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            Dict containing user data or None if user not found
        """
        try:
            response = self.supabase.auth.admin.get_user_by_id(user_id)
            if response.user:
                return {
                    "user_id": response.user.id,
                    "email": response.user.email,
                    "created_at": response.user.created_at,
                    "user_metadata": response.user.user_metadata,
                    "app_metadata": response.user.app_metadata
                }
            return None
        except Exception as e:
            print(f"Error getting user: {e}")
            return None
    
    def create_user_profile(self, user_id: str, email: str, metadata: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """
        Create or update user profile in the profiles table.
        
        Args:
            user_id: The user's unique identifier
            email: User's email address
            metadata: Additional user metadata (optional)
            
        Returns:
            Dict containing created profile data or None if failed
        """
        try:
            profile_data = {
                "id": user_id,
                "email": email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            if metadata:
                profile_data.update({
                    "full_name": metadata.get("full_name"),
                    "avatar_url": metadata.get("avatar_url"),
                    "provider": metadata.get("provider")
                })

            # Upsert user profile
            response = self.supabase.table("profiles").upsert(profile_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error creating user profile: {e}")
            return None