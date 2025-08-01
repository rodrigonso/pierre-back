"""
Subscription Service for Pierre Platform

This service handles:
- Usage tracking for Pierre requests
- Subscription validation
- Free request limit enforcement
- Subscription status management
"""

from typing import Dict, Any, Optional
from supabase import Client, acreate_client
from services.logger import get_logger_service
from utils.models import User
import os

logger_service = get_logger_service()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

class SubscriptionService:
    """Service for managing user subscriptions and usage tracking"""
    
    def __init__(self):
        if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
            raise ValueError("Missing Supabase configuration in environment variables")
    
    async def can_user_make_request(self, user: User) -> Dict[str, Any]:
        """
        Check if user can make a Pierre request
        
        Args:
            user: User object with subscription info
            
        Returns:
            Dict containing can_make_request (bool) and reason (str)
        """
        try:
            # Premium/Pro users have unlimited access
            if user.subscription_status in ['premium', 'pro']:
                return {
                    "can_make_request": True,
                    "reason": f"User has {user.subscription_status} subscription",
                    "remaining_requests": -1  # Unlimited
                }
            
            # Free users check their limit
            if user.free_requests_used >= user.free_requests_limit:
                return {
                    "can_make_request": False,
                    "reason": f"Free request limit exceeded ({user.free_requests_used}/{user.free_requests_limit})",
                    "remaining_requests": 0
                }
            
            remaining = user.free_requests_limit - user.free_requests_used
            return {
                "can_make_request": True,
                "reason": f"Free requests available ({user.free_requests_used}/{user.free_requests_limit})",
                "remaining_requests": remaining
            }
            
        except Exception as e:
            logger_service.error(f"Error checking user request eligibility: {str(e)}")
            return {
                "can_make_request": False,
                "reason": "Error validating subscription status",
                "remaining_requests": 0
            }
    
    async def increment_usage(self, user_id: str, request_type: str = "stylist_request") -> Dict[str, Any]:
        """
        Increment usage count for a user
        
        Args:
            user_id: User's UUID
            request_type: Type of request (default: stylist_request)
            
        Returns:
            Dict with success status and new usage count
        """
        try:
            supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            # Call the database function to increment usage
            result = await supabase_client.rpc(
                'increment_pierre_usage',
                {'user_uuid': user_id, 'req_type': request_type}
            ).execute()
            
            if result.data is not None:
                new_count = result.data
                logger_service.info(f"Incremented usage for user {user_id}: {new_count} total requests")
                return {
                    "success": True,
                    "new_count": new_count,
                    "message": f"Usage incremented to {new_count}"
                }
            else:
                logger_service.error(f"Failed to increment usage for user {user_id}")
                return {
                    "success": False,
                    "error": "Failed to increment usage count"
                }
                
        except Exception as e:
            logger_service.error(f"Error incrementing usage for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_user_usage(self, user_id: str) -> Dict[str, Any]:
        """
        Get current usage statistics for a user
        
        Args:
            user_id: User's UUID
            
        Returns:
            Dict with usage statistics
        """
        try:
            supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            # Get user profile with subscription info
            profile_response = await supabase_client.table("profiles").select(
                "subscription_status, free_requests_used, free_requests_limit"
            ).eq("id", user_id).execute()
            
            # Get detailed usage from usage table
            usage_response = await supabase_client.table("pierre_request_usage").select(
                "request_type, request_count, last_request_at"
            ).eq("user_id", user_id).execute()
            
            if not profile_response.data:
                return {
                    "success": False,
                    "error": "User profile not found"
                }
            
            profile = profile_response.data[0]
            usage_details = usage_response.data if usage_response.data else []
            
            return {
                "success": True,
                "user_id": user_id,
                "subscription_status": profile["subscription_status"],
                "free_requests_used": profile["free_requests_used"],
                "free_requests_limit": profile["free_requests_limit"],
                "remaining_free_requests": max(0, profile["free_requests_limit"] - profile["free_requests_used"]),
                "usage_details": usage_details
            }
            
        except Exception as e:
            logger_service.error(f"Error getting usage for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def upgrade_subscription(self, user_id: str, subscription_type: str) -> Dict[str, Any]:
        """
        Upgrade user's subscription (placeholder for Stripe integration)
        
        Args:
            user_id: User's UUID
            subscription_type: New subscription type ('premium' or 'pro')
            
        Returns:
            Dict with operation result
        """
        try:
            if subscription_type not in ['premium', 'pro']:
                return {
                    "success": False,
                    "error": "Invalid subscription type. Must be 'premium' or 'pro'"
                }
            
            supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            # Update user's subscription status
            result = await supabase_client.table("profiles").update({
                "subscription_status": subscription_type
            }).eq("id", user_id).execute()
            
            if result.data:
                logger_service.info(f"Upgraded user {user_id} to {subscription_type}")
                
                # Also update or create subscription record
                await supabase_client.table("user_subscriptions").upsert({
                    "user_id": user_id,
                    "subscription_type": subscription_type,
                    "status": "active"
                }).execute()
                
                return {
                    "success": True,
                    "message": f"Successfully upgraded to {subscription_type}",
                    "subscription_type": subscription_type
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to update subscription status"
                }
                
        except Exception as e:
            logger_service.error(f"Error upgrading subscription for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

# Singleton instance
_subscription_service = None

def get_subscription_service() -> SubscriptionService:
    """Get subscription service instance"""
    global _subscription_service
    if _subscription_service is None:
        _subscription_service = SubscriptionService()
    return _subscription_service
