-- Pierre Fashion Platform - Auto Profile Creation Migration
-- Migration: 002_auto_profile_creation
-- Created: 2025-06-23
-- Description: Creates a trigger function to automatically insert a new profile 
--              whenever a new user is created in Supabase Auth

-- ============================================================================
-- AUTO PROFILE CREATION FUNCTION
-- ============================================================================

-- Function to handle new user signup by creating a profile
-- This function will be called by Supabase Auth hooks
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    -- Insert a new profile for the newly created user
    INSERT INTO public.profiles (id, created_at, updated_at)
    VALUES (
        NEW.id,
        NOW(),
        NOW()
    );
    
    RETURN NEW;
EXCEPTION
    WHEN others THEN
        -- Log the error but don't fail the user creation
        RAISE LOG 'Error creating profile for user %: %', NEW.id, SQLERRM;
        RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- ALTERNATIVE: DATABASE WEBHOOK FUNCTION
-- ============================================================================

-- Alternative function that can be called via database webhooks
-- This is the Supabase-recommended approach for auth events
CREATE OR REPLACE FUNCTION public.create_profile_for_user(user_id uuid)
RETURNS void AS $$
BEGIN
    INSERT INTO public.profiles (id, created_at, updated_at)
    VALUES (
        user_id,
        NOW(),
        NOW()
    )
    ON CONFLICT (id) DO NOTHING; -- Prevent duplicate profiles
EXCEPTION
    WHEN others THEN
        RAISE LOG 'Error creating profile for user %: %', user_id, SQLERRM;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- TRIGGER SETUP (If permissions allow)
-- ============================================================================

-- Note: This trigger creation might fail due to permissions on auth.users
-- In that case, use the database webhook approach instead
DO $$
BEGIN
    CREATE TRIGGER on_auth_user_created
        AFTER INSERT ON auth.users
        FOR EACH ROW 
        EXECUTE FUNCTION public.handle_new_user();
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'Cannot create trigger on auth.users due to permissions. Use database webhooks instead.';
    WHEN others THEN
        RAISE NOTICE 'Trigger creation failed: %. Use database webhooks instead.', SQLERRM;
END;
$$;

-- ============================================================================
-- SECURITY AND PERMISSIONS
-- ============================================================================

-- Grant necessary permissions for the functions to work
GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
GRANT INSERT ON public.profiles TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.handle_new_user() TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.create_profile_for_user(uuid) TO supabase_auth_admin;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================

COMMENT ON FUNCTION public.handle_new_user() IS 
'Automatically creates a profile record when a new user signs up through Supabase Auth';

COMMENT ON TRIGGER on_auth_user_created ON auth.users IS 
'Trigger that automatically creates a profile for new users';
