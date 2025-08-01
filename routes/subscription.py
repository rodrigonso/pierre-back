"""
Subscription Routes for Pierre Platform

Endpoints for managing user subscriptions and usage:
- Check subscription status and usage
- Get upgrade options
- Manage subscription (placeholder for Stripe integration)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

from utils.models import User
from utils.auth import get_current_user
from services.subscription import get_subscription_service
from services.logger import get_logger_service

# Create router for subscription endpoints
router = APIRouter()
logger_service = get_logger_service()
subscription_service = get_subscription_service()

# ============================================================================
# PYDANTIC MODELS FOR REQUEST/RESPONSE
# ============================================================================

class SubscriptionStatusResponse(BaseModel):
    """Response model for subscription status"""
    user_id: str
    subscription_status: str
    free_requests_used: int
    free_requests_limit: int
    remaining_free_requests: int
    can_make_request: bool
    upgrade_required: bool

class UsageStatsResponse(BaseModel):
    """Response model for detailed usage statistics"""
    user_id: str
    subscription_status: str
    free_requests_used: int
    free_requests_limit: int
    remaining_free_requests: int
    usage_details: list
    last_request_info: Optional[Dict[str, Any]] = None

class UpgradeRequest(BaseModel):
    """Request model for subscription upgrade"""
    subscription_type: str  # 'premium' or 'pro'
    payment_method_id: Optional[str] = None  # For Stripe integration

class UpgradeResponse(BaseModel):
    """Response model for subscription upgrade"""
    success: bool
    message: str
    subscription_type: Optional[str] = None
    payment_required: bool = False
    client_secret: Optional[str] = None  # For Stripe payment intent

# ============================================================================
# SUBSCRIPTION STATUS ENDPOINTS
# ============================================================================

@router.get("/subscription/status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(user: User = Depends(get_current_user)):
    """
    Get current subscription status and usage for the authenticated user
    
    Returns:
        SubscriptionStatusResponse: User's subscription and usage details
    """
    try:
        logger_service.info(f"Getting subscription status for user: {user.id}")
        
        # Check if user can make requests
        access_check = await subscription_service.can_user_make_request(user)
        
        return SubscriptionStatusResponse(
            user_id=user.id,
            subscription_status=user.subscription_status,
            free_requests_used=user.free_requests_used,
            free_requests_limit=user.free_requests_limit,
            remaining_free_requests=user.get_remaining_free_requests(),
            can_make_request=access_check["can_make_request"],
            upgrade_required=not access_check["can_make_request"] and user.subscription_status == "free"
        )
        
    except Exception as e:
        logger_service.error(f"Error getting subscription status for user {user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve subscription status"
        )

@router.get("/subscription/usage", response_model=UsageStatsResponse)
async def get_usage_stats(user: User = Depends(get_current_user)):
    """
    Get detailed usage statistics for the authenticated user
    
    Returns:
        UsageStatsResponse: Detailed usage statistics
    """
    try:
        logger_service.info(f"Getting usage stats for user: {user.id}")
        
        # Get detailed usage from service
        usage_data = await subscription_service.get_user_usage(user.id)
        
        if not usage_data["success"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=usage_data["error"]
            )
        
        # Find last request info
        last_request_info = None
        if usage_data["usage_details"]:
            for detail in usage_data["usage_details"]:
                if detail.get("last_request_at"):
                    last_request_info = {
                        "request_type": detail["request_type"],
                        "last_request_at": detail["last_request_at"],
                        "total_requests": detail["request_count"]
                    }
                    break
        
        return UsageStatsResponse(
            user_id=user.id,
            subscription_status=usage_data["subscription_status"],
            free_requests_used=usage_data["free_requests_used"],
            free_requests_limit=usage_data["free_requests_limit"],
            remaining_free_requests=usage_data["remaining_free_requests"],
            usage_details=usage_data["usage_details"],
            last_request_info=last_request_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error getting usage stats for user {user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage statistics"
        )

# ============================================================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/subscription/plans")
async def get_subscription_plans():
    """
    Get available subscription plans and pricing
    
    Returns:
        Dict: Available subscription plans with features and pricing
    """
    return {
        "plans": {
            "free": {
                "name": "Free",
                "price": 0,
                "currency": "USD",
                "billing_period": "lifetime",
                "features": [
                    "4 free Pierre styling requests",
                    "Basic outfit recommendations",
                    "Access to product search"
                ],
                "limitations": [
                    "Limited to 4 total requests",
                    "No priority support"
                ]
            },
            "premium": {
                "name": "Premium",
                "price": 9.99,
                "currency": "USD",
                "billing_period": "monthly",
                "features": [
                    "Unlimited Pierre styling requests",
                    "Advanced outfit recommendations",
                    "Priority customer support",
                    "Exclusive brand partnerships",
                    "Style preference learning"
                ],
                "popular": True
            },
            "pro": {
                "name": "Pro",
                "price": 19.99,
                "currency": "USD",
                "billing_period": "monthly",
                "features": [
                    "Everything in Premium",
                    "Personal stylist consultations",
                    "Early access to new features",
                    "Custom style reports",
                    "API access for developers"
                ]
            }
        }
    }

@router.post("/subscription/upgrade", response_model=UpgradeResponse)
async def upgrade_subscription(
    upgrade_request: UpgradeRequest,
    user: User = Depends(get_current_user)
):
    """
    Upgrade user's subscription (placeholder - integrate with Stripe)
    
    Args:
        upgrade_request: Subscription upgrade details
        user: Authenticated user
        
    Returns:
        UpgradeResponse: Result of upgrade attempt
    """
    try:
        logger_service.info(f"Processing subscription upgrade for user {user.id} to {upgrade_request.subscription_type}")
        
        # Validate subscription type
        if upgrade_request.subscription_type not in ['premium', 'pro']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid subscription type. Must be 'premium' or 'pro'"
            )
        
        # Check if user is already on this plan or higher
        if user.subscription_status == upgrade_request.subscription_type:
            return UpgradeResponse(
                success=False,
                message=f"User is already on {upgrade_request.subscription_type} plan",
                subscription_type=user.subscription_status,
                payment_required=False
            )
        
        if user.subscription_status == 'pro' and upgrade_request.subscription_type == 'premium':
            return UpgradeResponse(
                success=False,
                message="Cannot downgrade from Pro to Premium. Please contact support.",
                subscription_type=user.subscription_status,
                payment_required=False
            )
        
        # TODO: Integrate with Stripe for actual payment processing
        # For now, we'll simulate a successful upgrade
        logger_service.warning("DEMO MODE: Simulating successful subscription upgrade without payment")
        
        # Update subscription in database
        upgrade_result = await subscription_service.upgrade_subscription(
            user.id, 
            upgrade_request.subscription_type
        )
        
        if upgrade_result["success"]:
            logger_service.success(f"Successfully upgraded user {user.id} to {upgrade_request.subscription_type}")
            return UpgradeResponse(
                success=True,
                message=f"Successfully upgraded to {upgrade_request.subscription_type}",
                subscription_type=upgrade_request.subscription_type,
                payment_required=False  # Set to True when Stripe is integrated
            )
        else:
            logger_service.error(f"Failed to upgrade user {user.id}: {upgrade_result['error']}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=upgrade_result["error"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error processing subscription upgrade for user {user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process subscription upgrade"
        )

@router.post("/subscription/cancel")
async def cancel_subscription(user: User = Depends(get_current_user)):
    """
    Cancel user's subscription (placeholder - integrate with Stripe)
    
    Args:
        user: Authenticated user
        
    Returns:
        Dict: Cancellation result
    """
    try:
        logger_service.info(f"Processing subscription cancellation for user {user.id}")
        
        if user.subscription_status == "free":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already on free plan"
            )
        
        # TODO: Integrate with Stripe for actual cancellation
        logger_service.warning("DEMO MODE: Simulating subscription cancellation")
        
        # For now, just set user back to free
        downgrade_result = await subscription_service.upgrade_subscription(user.id, "free")
        
        if downgrade_result["success"]:
            return {
                "success": True,
                "message": "Subscription cancelled successfully. You will retain access until the end of your billing period.",
                "new_status": "free"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel subscription"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error cancelling subscription for user {user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel subscription"
        )
