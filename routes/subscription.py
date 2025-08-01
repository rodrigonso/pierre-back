"""
Subscription Routes for Pierre Platform

Endpoints for managing user subscriptions and usage:
- Check subscription status and usage
- Get upgrade options
- Manage subscription with Stripe integration
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
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

class PaymentIntentRequest(BaseModel):
    """Request model for creating payment intent"""
    subscription_type: str  # 'premium' or 'pro'

class PaymentIntentResponse(BaseModel):
    """Response model for payment intent creation"""
    success: bool
    client_secret: Optional[str] = None
    payment_intent_id: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    error: Optional[str] = None

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
    Get available subscription plans and pricing from Stripe
    
    Returns:
        Dict: Available subscription plans with features and pricing
    """
    try:
        logger_service.info("Fetching subscription plans from Stripe")
        
        # Get plans from subscription service (which handles Stripe integration)
        plans_result = await subscription_service.get_stripe_plans()
        
        return plans_result
        
    except Exception as e:
        logger_service.error(f"Error fetching subscription plans: {str(e)}")

# ============================================================================
# STRIPE PAYMENT ENDPOINTS
# ============================================================================

@router.post("/subscription/create-payment-intent", response_model=PaymentIntentResponse)
async def create_payment_intent(
    payment_request: PaymentIntentRequest,
    user: User = Depends(get_current_user)
):
    """
    Create a Stripe Payment Intent for subscription upgrade
    
    Args:
        payment_request: Payment intent creation details
        user: Authenticated user
        
    Returns:
        PaymentIntentResponse: Payment intent details for client-side processing
    """
    try:
        logger_service.info(f"Creating payment intent for user {user.id} - {payment_request.subscription_type}")
        
        # Validate subscription type
        if payment_request.subscription_type not in ['premium', 'pro']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid subscription type. Must be 'premium' or 'pro'"
            )
        
        # Check if user is already on this plan or higher
        if user.subscription_status == payment_request.subscription_type:
            return PaymentIntentResponse(
                success=False,
                error=f"User is already on {payment_request.subscription_type} plan"
            )
        
        if user.subscription_status == 'pro' and payment_request.subscription_type == 'premium':
            return PaymentIntentResponse(
                success=False,
                error="Cannot downgrade from Pro to Premium"
            )
        
        # Create payment intent
        result = await subscription_service.create_payment_intent(
            user.id, 
            payment_request.subscription_type
        )
        
        if result["success"]:
            return PaymentIntentResponse(
                success=True,
                client_secret=result["client_secret"],
                payment_intent_id=result["payment_intent_id"],
                amount=result["amount"],
                currency=result["currency"]
            )
        else:
            return PaymentIntentResponse(
                success=False,
                error=result["error"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error creating payment intent for user {user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create payment intent"
        )

@router.post("/subscription/webhook")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events
    
    Args:
        request: FastAPI request object containing webhook payload
        
    Returns:
        Dict: Webhook processing result
    """
    try:
        payload = await request.body()
        signature = request.headers.get("stripe-signature")
        
        if not signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe signature header"
            )
        
        # Process webhook
        result = await subscription_service.handle_stripe_webhook(payload, signature)
        
        if result["success"]:
            logger_service.info(f"Successfully processed webhook event: {result.get('event_type')}")
            return {"received": True}
        else:
            logger_service.error(f"Failed to process webhook: {result['error']}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error processing Stripe webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process webhook"
        )

@router.post("/subscription/upgrade", response_model=UpgradeResponse)
async def upgrade_subscription(
    upgrade_request: UpgradeRequest,
    user: User = Depends(get_current_user)
):
    """
    Upgrade user's subscription with Stripe integration
    
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
        
        # For paid subscriptions, require payment processing
        logger_service.info("Paid subscription upgrade requires payment intent creation")
        
        return UpgradeResponse(
            success=False,
            message=f"Payment required for {upgrade_request.subscription_type} subscription. Please use the payment intent endpoint.",
            subscription_type=user.subscription_status,
            payment_required=True
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
    Cancel user's subscription with Stripe integration
    
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
        
        # Cancel Stripe subscription
        cancel_result = await subscription_service.cancel_stripe_subscription(user.id)
        
        if cancel_result["success"]:
            return {
                "success": True,
                "message": cancel_result["message"],
                "new_status": "free",
                "cancelled_subscriptions": cancel_result.get("cancelled_subscriptions", 0),
                "effective_immediately": cancel_result.get("effective_immediately", True)
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=cancel_result["error"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error cancelling subscription for user {user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel subscription"
        )

@router.post("/subscription/sync")
async def sync_subscription_status(user: User = Depends(get_current_user)):
    """
    Sync subscription status with Stripe
    
    Args:
        user: Authenticated user
        
    Returns:
        Dict: Sync result
    """
    try:
        logger_service.info(f"Syncing subscription status for user {user.id}")
        
        sync_result = await subscription_service.sync_subscription_status(user.id)
        
        if sync_result["success"]:
            return {
                "success": True,
                "local_status": sync_result["local_status"],
                "stripe_status": sync_result["stripe_status"],
                "synced": sync_result["synced"],
                "message": sync_result["message"],
                "updated_to": sync_result.get("updated_to")
            }
        else:
            return {
                "success": False,
                "error": sync_result["error"],
                "local_status": sync_result.get("local_status"),
                "stripe_status": sync_result.get("stripe_status")
            }
            
    except Exception as e:
        logger_service.error(f"Error syncing subscription for user {user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync subscription status"
        )
