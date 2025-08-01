-- Pierre Fashion Platform - Subscription System Migration
-- Migration: 005_subscription_system
-- Created: 2025-08-01
-- Description: Adds subscription tracking and usage limiting for Pierre requests

-- ============================================================================
-- USER SUBSCRIPTIONS TABLE
-- ============================================================================
-- Tracks user subscription status and billing information
CREATE TABLE IF NOT EXISTS public.user_subscriptions (
    id uuid NOT NULL DEFAULT uuid_generate_v4(),
    user_id uuid NOT NULL,
    subscription_type text NOT NULL DEFAULT 'free',
    status text NOT NULL DEFAULT 'active',
    stripe_customer_id text NULL,
    stripe_subscription_id text NULL,
    current_period_start timestamp with time zone NULL,
    current_period_end timestamp with time zone NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    
    CONSTRAINT user_subscriptions_pkey PRIMARY KEY (id),
    CONSTRAINT user_subscriptions_user_id_fkey FOREIGN KEY (user_id) 
        REFERENCES public.profiles (id) ON DELETE CASCADE,
    CONSTRAINT user_subscriptions_user_id_unique UNIQUE (user_id),
    CONSTRAINT user_subscriptions_type_check CHECK (subscription_type IN ('free', 'premium', 'pro')),
    CONSTRAINT user_subscriptions_status_check CHECK (status IN ('active', 'canceled', 'past_due', 'unpaid'))
) TABLESPACE pg_default;

-- ============================================================================
-- PIERRE REQUEST USAGE TABLE
-- ============================================================================
-- Tracks usage of Pierre AI requests per user
CREATE TABLE IF NOT EXISTS public.pierre_request_usage (
    id uuid NOT NULL DEFAULT uuid_generate_v4(),
    user_id uuid NOT NULL,
    request_type text NOT NULL DEFAULT 'stylist_request',
    request_count integer NOT NULL DEFAULT 0,
    last_request_at timestamp with time zone NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    
    CONSTRAINT pierre_request_usage_pkey PRIMARY KEY (id),
    CONSTRAINT pierre_request_usage_user_id_fkey FOREIGN KEY (user_id) 
        REFERENCES public.profiles (id) ON DELETE CASCADE,
    CONSTRAINT pierre_request_usage_user_type_unique UNIQUE (user_id, request_type),
    CONSTRAINT pierre_request_usage_count_check CHECK (request_count >= 0)
) TABLESPACE pg_default;

-- ============================================================================
-- ADD SUBSCRIPTION FIELDS TO PROFILES
-- ============================================================================
-- Add subscription-related fields to existing profiles table
ALTER TABLE public.profiles 
ADD COLUMN IF NOT EXISTS free_requests_used integer NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS free_requests_limit integer NOT NULL DEFAULT 4,
ADD COLUMN IF NOT EXISTS subscription_status text NOT NULL DEFAULT 'free';

-- Add constraint for subscription status
ALTER TABLE public.profiles 
ADD CONSTRAINT profiles_subscription_status_check 
CHECK (subscription_status IN ('free', 'premium', 'pro')) NOT VALID;

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================
-- Index for fast user subscription lookups
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_id 
ON public.user_subscriptions (user_id);

-- Index for fast usage lookups
CREATE INDEX IF NOT EXISTS idx_pierre_request_usage_user_id 
ON public.pierre_request_usage (user_id);

-- Index for subscription status queries
CREATE INDEX IF NOT EXISTS idx_profiles_subscription_status 
ON public.profiles (subscription_status);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================
-- Enable RLS on new tables
ALTER TABLE public.user_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pierre_request_usage ENABLE ROW LEVEL SECURITY;

-- Users can only see their own subscription data
CREATE POLICY "Users can view own subscription" ON public.user_subscriptions
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can update own subscription" ON public.user_subscriptions
    FOR UPDATE USING (auth.uid() = user_id);

-- Users can only see their own usage data
CREATE POLICY "Users can view own usage" ON public.pierre_request_usage
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can update own usage" ON public.pierre_request_usage
    FOR UPDATE USING (auth.uid() = user_id);

-- Service role can manage all subscription and usage data
CREATE POLICY "Service role full access subscriptions" ON public.user_subscriptions
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access usage" ON public.pierre_request_usage
    FOR ALL USING (auth.role() = 'service_role');

-- ============================================================================
-- FUNCTIONS FOR USAGE TRACKING
-- ============================================================================
-- Function to initialize user subscription and usage records
CREATE OR REPLACE FUNCTION initialize_user_subscription(user_uuid uuid)
RETURNS void AS $$
BEGIN
    -- Insert subscription record if it doesn't exist
    INSERT INTO public.user_subscriptions (user_id, subscription_type, status)
    VALUES (user_uuid, 'free', 'active')
    ON CONFLICT (user_id) DO NOTHING;
    
    -- Insert usage tracking record if it doesn't exist
    INSERT INTO public.pierre_request_usage (user_id, request_type, request_count)
    VALUES (user_uuid, 'stylist_request', 0)
    ON CONFLICT (user_id, request_type) DO NOTHING;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to increment usage count
CREATE OR REPLACE FUNCTION increment_pierre_usage(user_uuid uuid, req_type text DEFAULT 'stylist_request')
RETURNS integer AS $$
DECLARE
    new_count integer;
BEGIN
    -- Update usage count and get new value
    UPDATE public.pierre_request_usage 
    SET 
        request_count = request_count + 1,
        last_request_at = now(),
        updated_at = now()
    WHERE user_id = user_uuid AND request_type = req_type
    RETURNING request_count INTO new_count;
    
    -- If no record exists, create it
    IF new_count IS NULL THEN
        INSERT INTO public.pierre_request_usage (user_id, request_type, request_count, last_request_at)
        VALUES (user_uuid, req_type, 1, now())
        RETURNING request_count INTO new_count;
    END IF;
    
    -- Also update the profiles table free_requests_used
    UPDATE public.profiles 
    SET free_requests_used = LEAST(free_requests_used + 1, free_requests_limit)
    WHERE id = user_uuid;
    
    RETURN new_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to check if user can make a Pierre request
CREATE OR REPLACE FUNCTION can_make_pierre_request(user_uuid uuid)
RETURNS boolean AS $$
DECLARE
    user_subscription_type text;
    user_free_requests_used integer;
    user_free_requests_limit integer;
BEGIN
    -- Get user subscription and usage info
    SELECT 
        p.subscription_status,
        p.free_requests_used,
        p.free_requests_limit
    INTO 
        user_subscription_type,
        user_free_requests_used,
        user_free_requests_limit
    FROM public.profiles p
    WHERE p.id = user_uuid;
    
    -- If user has premium/pro subscription, they can always make requests
    IF user_subscription_type IN ('premium', 'pro') THEN
        RETURN true;
    END IF;
    
    -- For free users, check if they haven't exceeded their limit
    RETURN user_free_requests_used < user_free_requests_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- TRIGGER TO AUTO-INITIALIZE SUBSCRIPTION FOR NEW USERS
-- ============================================================================
-- Function to auto-initialize subscription when profile is created
CREATE OR REPLACE FUNCTION auto_initialize_subscription()
RETURNS trigger AS $$
BEGIN
    PERFORM initialize_user_subscription(NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to auto-initialize subscription for new profiles
CREATE TRIGGER trigger_auto_initialize_subscription
    AFTER INSERT ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION auto_initialize_subscription();

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================
-- Grant necessary permissions to authenticated users
GRANT SELECT, UPDATE ON public.user_subscriptions TO authenticated;
GRANT SELECT, UPDATE ON public.pierre_request_usage TO authenticated;

-- Grant execute permissions on functions
GRANT EXECUTE ON FUNCTION initialize_user_subscription(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_pierre_usage(uuid, text) TO authenticated;
GRANT EXECUTE ON FUNCTION can_make_pierre_request(uuid) TO authenticated;
