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
import stripe
from datetime import datetime, timezone

logger_service = get_logger_service()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# Stripe configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Configure Stripe
stripe.api_key = STRIPE_SECRET_KEY

class SubscriptionService:
    """Service for managing user subscriptions and usage tracking"""
    
    def __init__(self):
        if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
            raise ValueError("Missing Supabase configuration in environment variables")
        
        if not STRIPE_SECRET_KEY:
            logger_service.warning("Missing Stripe configuration - payments will not work")
        else:
            logger_service.info("Stripe integration initialized successfully")
    
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
    
    async def get_stripe_plans(self) -> Dict[str, Any]:
        """
        Get subscription plans from Stripe Products and Prices
        
        Returns:
            Dict with plans structure or fallback to hardcoded plans
        """
        try:
            if not STRIPE_SECRET_KEY:
                logger_service.warning("Stripe not configured, returning hardcoded plans")
                return self._get_fallback_plans()
            
            # Fetch all active products from Stripe
            products = stripe.Product.list(active=True, limit=10)
            
            # Fetch all active prices from Stripe
            prices = stripe.Price.list(active=True, limit=20)
            
            # Create a mapping of price_id to product for easy lookup
            price_to_product = {}
            product_prices = {}
            
            # Group prices by product
            for price in prices.data:
                product_id = price.product
                if product_id not in product_prices:
                    product_prices[product_id] = []
                product_prices[product_id].append(price)
                price_to_product[price.id] = product_id
            
            plans = {}
            
            # Process each product
            for product in products.data:
                product_id = product.id
                product_name = product.name.lower()
                
                # Map product names to our plan types
                plan_key = None
                if 'free' in product_name:
                    plan_key = 'free'
                elif 'elevate' in product_name:
                    plan_key = 'premium'
                elif 'expert' in product_name:
                    plan_key = 'pro'
                
                if not plan_key:
                    continue
                
                # Get the primary price for this product
                product_price_list = product_prices.get(product_id, [])
                primary_price = None
                
                # Prefer monthly recurring prices
                for price in product_price_list:
                    if price.type == 'recurring' and price.recurring.interval == 'month':
                        primary_price = price
                        break
                
                # Fallback to any price if no monthly found
                if not primary_price and product_price_list:
                    primary_price = product_price_list[0]
                
                # Build plan structure
                plan_data = {
                    "name": product.name,
                    "price": (primary_price.unit_amount / 100) if primary_price and primary_price.unit_amount else 0,
                    "currency": primary_price.currency.upper() if primary_price else "USD",
                    "billing_period": "monthly" if primary_price and primary_price.type == 'recurring' else "lifetime",
                    "features": product.description.split('\n') if product.description else [],
                    "stripe_product_id": product.id,
                    "stripe_price_id": primary_price.id if primary_price else None
                }

                print(plan_data)
                
                # Add special attributes
                if plan_key == 'premium':
                    plan_data["popular"] = True
                elif plan_key == 'free':
                    plan_data["limitations"] = [
                        "Limited to 2 Pierre requests a month",
                        "Slower Pierre response times",
                    ]

                plans[plan_key] = plan_data

            # Ensure we have all required plans, fallback for missing ones
            fallback_plans = self._get_fallback_plans()["plans"]
            for required_plan in ['free', 'premium', 'pro']:
                if required_plan not in plans:
                    logger_service.warning(f"Plan '{required_plan}' not found in Stripe, using fallback")
                    plans[required_plan] = fallback_plans[required_plan]
            
            logger_service.info(f"Successfully fetched {len(plans)} plans from Stripe")
            return {"plans": plans}
            
        except Exception as e:
            logger_service.error(f"Error fetching Stripe plans: {str(e)}")
            logger_service.warning("Falling back to hardcoded plans")
            return self._get_fallback_plans()
    
    def _get_fallback_plans(self) -> Dict[str, Any]:
        """
        Get hardcoded fallback plans when Stripe is unavailable
        
        Returns:
            Dict with hardcoded plans structure
        """
        return {
            "plans": {
                "free": {
                    "name": "Free",
                    "price": 0,
                    "currency": "USD",
                    "billing_period": "lifetime",
                    "features": [
                        "2 free Pierre styling requests",
                        "Basic outfit recommendations",
                        "Access to product search"
                    ],
                    "limitations": [
                        "Limited to 2 total requests",
                        "Slower Pierre response times",
                    ]
                },
                "premium": {
                    "name": "Elevate",
                    "price": 3.99,
                    "currency": "USD",
                    "billing_period": "monthly",
                    "features": [
                        "Up to 10 Pierre styling requests per month",
                        "Advanced outfit recommendations",
                        "Faster Pierre response times",
                    ],
                    "popular": True
                },
                "pro": {
                    "name": "Expert",
                    "price": 9.99,
                    "currency": "USD",
                    "billing_period": "monthly",
                    "features": [
                        "Unlimited Pierre styling requests",
                        "Even faster Pierre response times",
                        "Access to deep fashion insights",
                        "Early access to new features",
                    ]
                }
            }
        }

    async def create_payment_intent(self, user_id: str, subscription_type: str, customer_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a Stripe Payment Intent for subscription upgrade
        
        Args:
            user_id: User's UUID
            subscription_type: Target subscription type ('premium' or 'pro')
            customer_id: Existing Stripe customer ID (optional)
            
        Returns:
            Dict with payment intent details or error
        """
        try:
            if not STRIPE_SECRET_KEY:
                return {
                    "success": False,
                    "error": "Stripe not configured"
                }
            
            # Get current plans from Stripe to get dynamic pricing
            plans_result = await self.get_stripe_plans()
            if not plans_result.get("plans", {}).get(subscription_type):
                return {
                    "success": False,
                    "error": f"Subscription type '{subscription_type}' not found"
                }
            
            plan = plans_result["plans"][subscription_type]
            
            # Convert price to cents for Stripe
            amount_in_cents = int(plan["price"] * 100)
            
            if amount_in_cents <= 0:
                return {
                    "success": False,
                    "error": f"Invalid price for {subscription_type} plan"
                }
            
            # Create or retrieve Stripe customer
            if not customer_id:
                # Get user profile for email
                supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
                profile_response = await supabase_client.table("profiles").select(
                    "email, full_name"
                ).eq("id", user_id).execute()
                
                if not profile_response.data:
                    return {
                        "success": False,
                        "error": "User profile not found"
                    }
                
                profile = profile_response.data[0]
                
                # Create Stripe customer
                customer = stripe.Customer.create(
                    email=profile.get("email"),
                    name=profile.get("full_name"),
                    metadata={"user_id": user_id}
                )
                customer_id = customer.id
                
                # Store customer ID in user profile
                await supabase_client.table("profiles").update({
                    "stripe_customer_id": customer_id
                }).eq("id", user_id).execute()
                
                logger_service.info(f"Created Stripe customer {customer_id} for user {user_id}")
            
            # Create payment intent
            intent = stripe.PaymentIntent.create(
                amount=amount_in_cents,
                currency=plan["currency"].lower(),
                customer=customer_id,
                metadata={
                    'user_id': user_id,
                    'subscription_type': subscription_type,
                    'upgrade_type': 'subscription'
                },
                description=f"Pierre {subscription_type.title()} Subscription"
            )
            
            logger_service.info(f"Created payment intent {intent.id} for user {user_id} - {subscription_type}")
            
            return {
                "success": True,
                "payment_intent_id": intent.id,
                "client_secret": intent.client_secret,
                "customer_id": customer_id,
                "amount": amount_in_cents,
                "currency": plan["currency"].lower()
            }
            
        except stripe.error.StripeError as e:
            logger_service.error(f"Stripe error creating payment intent for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Payment processing error: {str(e)}"
            }
        except Exception as e:
            logger_service.error(f"Error creating payment intent for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def handle_stripe_webhook(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """
        Handle and verify Stripe webhook events
        
        Args:
            payload: Raw webhook payload
            signature: Stripe signature header
            
        Returns:
            Dict with processing result
        """
        try:
            if not STRIPE_WEBHOOK_SECRET:
                logger_service.error("Stripe webhook secret not configured")
                return {
                    "success": False,
                    "error": "Webhook secret not configured"
                }
            
            # Verify webhook signature
            try:
                event = stripe.Webhook.construct_event(
                    payload, signature, STRIPE_WEBHOOK_SECRET
                )
            except ValueError as e:
                logger_service.error(f"Invalid webhook payload: {str(e)}")
                return {
                    "success": False,
                    "error": "Invalid payload"
                }
            except stripe.error.SignatureVerificationError as e:
                logger_service.error(f"Invalid webhook signature: {str(e)}")
                return {
                    "success": False,
                    "error": "Invalid signature"
                }
            
            logger_service.info(f"Received Stripe webhook event: {event['type']}")
            
            # Handle different event types
            if event['type'] == 'payment_intent.succeeded':
                await self._handle_payment_success(event['data']['object'])
            elif event['type'] == 'payment_intent.payment_failed':
                await self._handle_payment_failure(event['data']['object'])
            elif event['type'] == 'customer.subscription.created':
                await self._handle_subscription_created(event['data']['object'])
            elif event['type'] == 'customer.subscription.updated':
                await self._handle_subscription_updated(event['data']['object'])
            elif event['type'] == 'customer.subscription.deleted':
                await self._handle_subscription_cancelled(event['data']['object'])
            else:
                logger_service.info(f"Unhandled webhook event type: {event['type']}")
            
            return {
                "success": True,
                "event_type": event['type'],
                "processed": True
            }
            
        except Exception as e:
            logger_service.error(f"Error processing Stripe webhook: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _handle_payment_success(self, payment_intent: Dict[str, Any]) -> None:
        """Handle successful payment intent"""
        try:
            user_id = payment_intent['metadata'].get('user_id')
            subscription_type = payment_intent['metadata'].get('subscription_type')
            
            if not user_id or not subscription_type:
                logger_service.error("Missing metadata in payment intent")
                return
            
            # Upgrade user's subscription
            result = await self.upgrade_subscription(user_id, subscription_type)
            
            if result["success"]:
                logger_service.success(f"Successfully upgraded user {user_id} to {subscription_type} after payment")
                
                # Store payment record
                supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
                await supabase_client.table("payment_records").insert({
                    "user_id": user_id,
                    "stripe_payment_intent_id": payment_intent['id'],
                    "amount": payment_intent['amount'],
                    "currency": payment_intent['currency'],
                    "subscription_type": subscription_type,
                    "status": "succeeded",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }).execute()
                
            else:
                logger_service.error(f"Failed to upgrade user after payment: {result['error']}")
                
        except Exception as e:
            logger_service.error(f"Error handling payment success: {str(e)}")
    
    async def _handle_payment_failure(self, payment_intent: Dict[str, Any]) -> None:
        """Handle failed payment intent"""
        try:
            user_id = payment_intent['metadata'].get('user_id')
            logger_service.warning(f"Payment failed for user {user_id}: {payment_intent.get('last_payment_error', {}).get('message', 'Unknown error')}")
            
            # Store payment failure record
            if user_id:
                supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
                await supabase_client.table("payment_records").insert({
                    "user_id": user_id,
                    "stripe_payment_intent_id": payment_intent['id'],
                    "amount": payment_intent['amount'],
                    "currency": payment_intent['currency'],
                    "subscription_type": payment_intent['metadata'].get('subscription_type'),
                    "status": "failed",
                    "error_message": payment_intent.get('last_payment_error', {}).get('message'),
                    "created_at": datetime.now(timezone.utc).isoformat()
                }).execute()
                
        except Exception as e:
            logger_service.error(f"Error handling payment failure: {str(e)}")
    
    async def _handle_subscription_created(self, subscription: Dict[str, Any]) -> None:
        """Handle subscription creation (for recurring subscriptions)"""
        logger_service.info(f"Subscription created: {subscription['id']}")
        # Implement recurring subscription logic if needed
    
    async def _handle_subscription_updated(self, subscription: Dict[str, Any]) -> None:
        """Handle subscription updates"""  
        logger_service.info(f"Subscription updated: {subscription['id']}")
        # Implement subscription update logic if needed
    
    async def _handle_subscription_cancelled(self, subscription: Dict[str, Any]) -> None:
        """Handle subscription cancellation"""
        try:
            customer_id = subscription['customer']
            
            # Find user by Stripe customer ID
            supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            profile_response = await supabase_client.table("profiles").select(
                "id"
            ).eq("stripe_customer_id", customer_id).execute()
            
            if profile_response.data:
                user_id = profile_response.data[0]["id"]
                
                # Downgrade to free
                result = await self.upgrade_subscription(user_id, "free")
                
                if result["success"]:
                    logger_service.info(f"Successfully downgraded user {user_id} to free after subscription cancellation")
                else:
                    logger_service.error(f"Failed to downgrade user after cancellation: {result['error']}")
            
        except Exception as e:
            logger_service.error(f"Error handling subscription cancellation: {str(e)}")
    
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
    
    async def upgrade_subscription(self, user_id: str, subscription_type: str, skip_payment: bool = False) -> Dict[str, Any]:
        """
        Upgrade user's subscription
        
        Args:
            user_id: User's UUID
            subscription_type: New subscription type ('premium', 'pro', or 'free' for downgrades)
            skip_payment: Skip payment processing (for webhook-triggered upgrades)
            
        Returns:
            Dict with operation result
        """
        try:
            if subscription_type not in ['free', 'premium', 'pro']:
                return {
                    "success": False,
                    "error": "Invalid subscription type. Must be 'free', 'premium' or 'pro'"
                }
            
            supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            # For paid subscriptions, ensure payment is processed (unless skipped)
            if subscription_type in ['premium', 'pro'] and not skip_payment:
                logger_service.info(f"Subscription upgrade to {subscription_type} requires payment processing")
                return {
                    "success": False,
                    "error": "Payment required for subscription upgrade",
                    "requires_payment": True
                }
            
            # Update user's subscription status
            update_data = {
                "subscription_status": subscription_type,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            # If upgrading to premium/pro, reset any usage limits or add benefits
            if subscription_type in ['premium', 'pro']:
                update_data["subscription_upgraded_at"] = datetime.now(timezone.utc).isoformat()
            
            result = await supabase_client.table("profiles").update(update_data).eq("id", user_id).execute()
            
            if result.data:
                logger_service.info(f"Updated user {user_id} subscription status to {subscription_type}")
                
                # Create or update subscription record
                subscription_record = {
                    "user_id": user_id,
                    "subscription_type": subscription_type,
                    "status": "active" if subscription_type != "free" else "cancelled",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                
                # Check if subscription record exists
                existing_sub = await supabase_client.table("user_subscriptions").select("*").eq("user_id", user_id).execute()
                
                if existing_sub.data:
                    # Update existing record
                    await supabase_client.table("user_subscriptions").update(subscription_record).eq("user_id", user_id).execute()
                else:
                    # Create new record
                    subscription_record["created_at"] = datetime.now(timezone.utc).isoformat()
                    await supabase_client.table("user_subscriptions").insert(subscription_record).execute()
                
                return {
                    "success": True,
                    "message": f"Successfully {'upgraded' if subscription_type != 'free' else 'updated'} to {subscription_type}",
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
    
    async def cancel_stripe_subscription(self, user_id: str) -> Dict[str, Any]:
        """
        Cancel user's Stripe subscription
        
        Args:
            user_id: User's UUID
            
        Returns:
            Dict with cancellation result
        """
        try:
            if not STRIPE_SECRET_KEY:
                logger_service.warning("Stripe not configured - performing local cancellation only")
                return await self.upgrade_subscription(user_id, "free", skip_payment=True)
            
            supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            # Get user's Stripe customer ID
            profile_response = await supabase_client.table("profiles").select(
                "stripe_customer_id, subscription_status"
            ).eq("id", user_id).execute()
            
            if not profile_response.data:
                return {
                    "success": False,
                    "error": "User profile not found"
                }
            
            profile = profile_response.data[0]
            customer_id = profile.get("stripe_customer_id")
            current_status = profile.get("subscription_status", "free")
            
            if current_status == "free":
                return {
                    "success": False,
                    "error": "User is already on free plan"
                }
            
            if not customer_id:
                logger_service.warning(f"No Stripe customer ID found for user {user_id}, performing local cancellation")
                return await self.upgrade_subscription(user_id, "free", skip_payment=True)
            
            # Find and cancel active subscriptions
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='active'
            )
            
            cancelled_count = 0
            for subscription in subscriptions.data:
                try:
                    stripe.Subscription.delete(subscription.id)
                    cancelled_count += 1
                    logger_service.info(f"Cancelled Stripe subscription {subscription.id} for user {user_id}")
                except Exception as e:
                    logger_service.error(f"Failed to cancel Stripe subscription {subscription.id}: {str(e)}")
            
            # Update local subscription status
            local_result = await self.upgrade_subscription(user_id, "free", skip_payment=True)
            
            if local_result["success"]:
                return {
                    "success": True,
                    "message": f"Subscription cancelled successfully. Cancelled {cancelled_count} active subscriptions.",
                    "cancelled_subscriptions": cancelled_count,
                    "effective_immediately": True
                }
            else:
                return {
                    "success": False,
                    "error": f"Stripe cancellation succeeded but local update failed: {local_result['error']}"
                }
                
        except stripe.error.StripeError as e:
            logger_service.error(f"Stripe error cancelling subscription for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Payment processing error: {str(e)}"
            }
        except Exception as e:
            logger_service.error(f"Error cancelling subscription for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def sync_subscription_status(self, user_id: str) -> Dict[str, Any]:
        """
        Sync subscription status with Stripe
        
        Args:
            user_id: User's UUID
            
        Returns:
            Dict with sync result and current status
        """
        try:
            if not STRIPE_SECRET_KEY:
                logger_service.warning("Stripe not configured - cannot sync subscription status")
                return {
                    "success": False,
                    "error": "Stripe not configured"
                }
            
            supabase_client: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            
            # Get user's Stripe customer ID
            profile_response = await supabase_client.table("profiles").select(
                "stripe_customer_id, subscription_status"
            ).eq("id", user_id).execute()
            
            if not profile_response.data:
                return {
                    "success": False,
                    "error": "User profile not found"
                }
            
            profile = profile_response.data[0]
            customer_id = profile.get("stripe_customer_id")
            local_status = profile.get("subscription_status", "free")
            
            if not customer_id:
                logger_service.info(f"No Stripe customer ID for user {user_id}, assuming free status is correct")
                return {
                    "success": True,
                    "local_status": local_status,
                    "stripe_status": None,
                    "synced": True,
                    "message": "No Stripe customer - local status maintained"
                }
            
            # Get active subscriptions from Stripe
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='active',
                limit=10
            )
            
            # Determine Stripe status based on active subscriptions
            stripe_status = "free"
            if subscriptions.data:
                # For now, we'll take the highest tier subscription
                # You might want more sophisticated logic here
                subscription_tiers = {"premium": 1, "pro": 2}
                highest_tier = 0
                
                for sub in subscriptions.data:
                    # Check subscription metadata or price ID to determine tier
                    sub_type = sub.get('metadata', {}).get('subscription_type', 'premium')
                    if sub_type in subscription_tiers:
                        tier_level = subscription_tiers[sub_type]
                        if tier_level > highest_tier:
                            highest_tier = tier_level
                            stripe_status = sub_type
            
            # Compare and sync if necessary
            if local_status != stripe_status:
                logger_service.info(f"Status mismatch for user {user_id}: local={local_status}, stripe={stripe_status}")
                
                # Update local status to match Stripe
                sync_result = await self.upgrade_subscription(user_id, stripe_status, skip_payment=True)
                
                if sync_result["success"]:
                    return {
                        "success": True,
                        "local_status": local_status,
                        "stripe_status": stripe_status,
                        "synced": True,
                        "updated_to": stripe_status,
                        "message": f"Synced subscription status from {local_status} to {stripe_status}"
                    }
                else:
                    return {
                        "success": False,
                        "local_status": local_status,
                        "stripe_status": stripe_status,
                        "synced": False,
                        "error": f"Failed to sync status: {sync_result['error']}"
                    }
            else:
                return {
                    "success": True,
                    "local_status": local_status,
                    "stripe_status": stripe_status,
                    "synced": True,
                    "message": "Subscription status already in sync"
                }
                
        except stripe.error.StripeError as e:
            logger_service.error(f"Stripe error syncing subscription for user {user_id}: {str(e)}")
            return {
                "success": False,
                "error": f"Stripe error: {str(e)}"
            }
        except Exception as e:
            logger_service.error(f"Error syncing subscription for user {user_id}: {str(e)}")
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
