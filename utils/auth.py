from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from services.auth import AuthService
from supabase import Client
from typing import Dict, Any, Optional
from utils.models import User

security = HTTPBearer()
auth_service = AuthService()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[User]:
    """
    Dependency to get the current authenticated user.
    This should be used in route handlers that require authentication.
    
    Args:
        credentials: HTTP Bearer token credentials
        auth_service: Auth service instance (injected automatically)
        
    Returns:
        User: Authenticated user model or None if authentication fails
        
    Raises:
        HTTPException: If authentication fails or auth service not initialized
    """
    try:
        user = await auth_service.get_current_user(credentials.credentials)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

def create_response(
    success: bool = True,
    message: str = "",
    data: Any = None,
    error: str = None
) -> Dict[str, Any]:
    """
    Create a standardized API response format.
    """
    response = {
        "success": success,
        "message": message
    }
    
    if data is not None:
        response["data"] = data
    
    if error:
        response["error"] = error
    
    return response
