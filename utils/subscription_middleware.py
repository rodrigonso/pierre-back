"""
Subscription Middleware for Pierre Platform

This middleware:
- Checks user subscription status before processing Pierre requests
- Enforces free request limits
- Tracks usage automatically
- Returns appropriate error responses for limit exceeded
"""

from fastapi import HTTPException, status
from functools import wraps
from typing import Callable, Any
from utils.models import User
from services.subscription import get_subscription_service
from services.logger import get_logger_service

logger_service = get_logger_service()
subscription_service = get_subscription_service()

def require_pierre_access(request_type: str = "stylist_request"):
    """
    Decorator to enforce Pierre request limits and track usage
    
    Args:
        request_type: Type of Pierre request (default: stylist_request)
        
    Usage:
        @require_pierre_access("stylist_request")
        async def my_endpoint(user: User = Depends(get_current_user)):
            # This endpoint will be protected by usage limits
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Extract user from function arguments
            user = None
            for arg in args:
                if isinstance(arg, User):
                    user = arg
                    break
            
            # Also check kwargs for user
            if not user:
                user = kwargs.get('user')
            
            if not user:
                logger_service.error("Pierre access decorator applied to endpoint without User dependency")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal server error: Missing user context"
                )
            
            logger_service.info(f"Checking Pierre access for user {user.id} (request_type: {request_type})")
            
            # Check if user can make the request
            access_check = await subscription_service.can_user_make_request(user)
            
            if not access_check["can_make_request"]:
                logger_service.warning(f"Pierre request denied for user {user.id}: {access_check['reason']}")
                
                # Return specific error based on subscription status
                if user.subscription_status == "free":
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail={
                            "error": "Free request limit exceeded",
                            "message": f"You've used all {user.free_requests_limit} free Pierre requests. Upgrade to continue using Pierre's AI styling services.",
                            "free_requests_used": user.free_requests_used,
                            "free_requests_limit": user.free_requests_limit,
                            "subscription_required": True,
                            "upgrade_options": {
                                "premium": "Unlimited Pierre requests + priority support",
                                "pro": "Unlimited Pierre requests + priority support + advanced features"
                            }
                        }
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={
                            "error": "Access denied",
                            "message": access_check["reason"],
                            "subscription_status": user.subscription_status
                        }
                    )
            
            logger_service.info(f"Pierre access granted for user {user.id}: {access_check['reason']}")
            
            try:
                # Execute the original function
                result = await func(*args, **kwargs)
                
                # If the function executed successfully, increment usage
                logger_service.info(f"Pierre request completed successfully for user {user.id}, incrementing usage")
                usage_result = await subscription_service.increment_usage(user.id, request_type)
                
                if usage_result["success"]:
                    logger_service.success(f"Usage incremented for user {user.id}: {usage_result['new_count']} total requests")
                else:
                    logger_service.error(f"Failed to increment usage for user {user.id}: {usage_result.get('error')}")
                
                return result
                
            except Exception as e:
                logger_service.error(f"Pierre request failed for user {user.id}: {str(e)}")
                # Don't increment usage if the request failed
                raise
        
        return wrapper
    return decorator

class PierreAccessMiddleware:
    """
    Alternative class-based middleware for Pierre access control
    Can be used as a dependency in FastAPI endpoints
    """
    
    def __init__(self, request_type: str = "stylist_request"):
        self.request_type = request_type
    
    async def __call__(self, user: User) -> User:
        """
        Validate user access and return user if allowed
        
        Args:
            user: Authenticated user
            
        Returns:
            User object if access is granted
            
        Raises:
            HTTPException: If access is denied
        """
        logger_service.info(f"Middleware checking Pierre access for user {user.id}")
        
        # Check if user can make the request
        access_check = await subscription_service.can_user_make_request(user)
        
        if not access_check["can_make_request"]:
            logger_service.warning(f"Pierre request denied for user {user.id}: {access_check['reason']}")
            
            if user.subscription_status == "free":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "Free request limit exceeded",
                        "message": f"You've used all {user.free_requests_limit} free Pierre requests. Upgrade to continue using Pierre's AI styling services.",
                        "free_requests_used": user.free_requests_used,
                        "free_requests_limit": user.free_requests_limit,
                        "remaining_requests": access_check["remaining_requests"],
                        "subscription_required": True
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "Access denied",
                        "message": access_check["reason"],
                        "subscription_status": user.subscription_status
                    }
                )
        
        logger_service.info(f"Pierre access granted for user {user.id}")
        return user

# Helper function to create middleware instances
def create_pierre_access_middleware(request_type: str = "stylist_request") -> PierreAccessMiddleware:
    """Create a Pierre access middleware instance for specific request type"""
    return PierreAccessMiddleware(request_type)

# Default middleware instance
pierre_access_middleware = create_pierre_access_middleware("stylist_request")
