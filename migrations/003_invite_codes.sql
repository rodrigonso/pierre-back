-- Migration: Add invite codes system
-- Description: Create invite_codes table with proper RLS policies and update profiles table

-- Create invite_codes table
CREATE TABLE IF NOT EXISTS public.invite_codes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    max_uses INTEGER DEFAULT 1 NOT NULL CHECK (max_uses > 0),
    current_uses INTEGER DEFAULT 0 NOT NULL CHECK (current_uses >= 0),
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    description TEXT,
    
    -- Ensure current_uses doesn't exceed max_uses
    CONSTRAINT check_uses_limit CHECK (current_uses <= max_uses)
);

-- Add invite_code_used column to profiles table to track which code was used
ALTER TABLE public.profiles 
ADD COLUMN IF NOT EXISTS invite_code_used VARCHAR(50) REFERENCES public.invite_codes(code) ON DELETE SET NULL;

-- Add index for better performance on code lookups
CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON public.invite_codes(code);
CREATE INDEX IF NOT EXISTS idx_invite_codes_active ON public.invite_codes(is_active, expires_at);
CREATE INDEX IF NOT EXISTS idx_profiles_invite_code ON public.profiles(invite_code_used);

-- Enable RLS on invite_codes table
ALTER TABLE public.invite_codes ENABLE ROW LEVEL SECURITY;

-- RLS Policies for invite_codes table

-- Policy 1: Anyone can read active, non-expired codes for validation
CREATE POLICY "Anyone can validate active invite codes" ON public.invite_codes
    FOR SELECT
    USING (
        is_active = TRUE 
        AND (expires_at IS NULL OR expires_at > NOW())
        AND current_uses < max_uses
    );

-- Policy 2: Authenticated users can create invite codes (admin function)
-- Note: You may want to restrict this further to specific admin roles
CREATE POLICY "Authenticated users can create invite codes" ON public.invite_codes
    FOR INSERT
    WITH CHECK (auth.uid() IS NOT NULL);

-- Policy 3: Code creators can view their own codes
CREATE POLICY "Users can view their own created codes" ON public.invite_codes
    FOR SELECT
    USING (created_by = auth.uid());

-- Policy 4: Code creators can update their own codes
CREATE POLICY "Users can update their own created codes" ON public.invite_codes
    FOR UPDATE
    USING (created_by = auth.uid())
    WITH CHECK (created_by = auth.uid());

-- Policy 5: System can update usage count (for the application to increment current_uses)
-- This will be handled by the service role in the backend
-- No additional policy needed as service role bypasses RLS

-- Create a function to validate and use an invite code
CREATE OR REPLACE FUNCTION public.use_invite_code(code_to_use VARCHAR(50))
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    code_record RECORD;
BEGIN
    -- Get the invite code with row locking to prevent race conditions
    SELECT * INTO code_record
    FROM public.invite_codes
    WHERE code = code_to_use
    FOR UPDATE;
    
    -- Check if code exists
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    
    -- Check if code is active
    IF NOT code_record.is_active THEN
        RETURN FALSE;
    END IF;
    
    -- Check if code has expired
    IF code_record.expires_at IS NOT NULL AND code_record.expires_at <= NOW() THEN
        RETURN FALSE;
    END IF;
    
    -- Check if code has remaining uses
    IF code_record.current_uses >= code_record.max_uses THEN
        RETURN FALSE;
    END IF;
    
    -- Increment usage count
    UPDATE public.invite_codes
    SET current_uses = current_uses + 1
    WHERE code = code_to_use;
    
    RETURN TRUE;
END;
$$;

-- Create a function to generate a random invite code
CREATE OR REPLACE FUNCTION public.generate_invite_code()
RETURNS VARCHAR(50)
LANGUAGE plpgsql
AS $$
DECLARE
    new_code VARCHAR(50);
    code_exists BOOLEAN;
BEGIN
    LOOP
        -- Generate a random 8-character alphanumeric code
        new_code := upper(substring(md5(random()::text) from 1 for 8));
        
        -- Check if this code already exists
        SELECT EXISTS(SELECT 1 FROM public.invite_codes WHERE code = new_code) INTO code_exists;
        
        -- If code doesn't exist, we can use it
        IF NOT code_exists THEN
            RETURN new_code;
        END IF;
    END LOOP;
END;
$$;

-- Insert some initial invite codes for testing (optional - remove in production)
-- INSERT INTO public.invite_codes (code, description, max_uses, created_by)
-- VALUES 
--     ('WELCOME2024', 'Initial launch invite code', 100, NULL),
--     ('BETA001', 'Beta tester invite code', 50, NULL);

COMMENT ON TABLE public.invite_codes IS 'System for managing invite-only access to the platform';
COMMENT ON COLUMN public.invite_codes.code IS 'Unique invite code string that users enter';
COMMENT ON COLUMN public.invite_codes.max_uses IS 'Maximum number of times this code can be used';
COMMENT ON COLUMN public.invite_codes.current_uses IS 'Current number of times this code has been used';
COMMENT ON COLUMN public.invite_codes.expires_at IS 'Optional expiration timestamp for the code';
COMMENT ON COLUMN public.invite_codes.is_active IS 'Whether the code is currently active and usable';
COMMENT ON COLUMN public.invite_codes.created_by IS 'User ID of who created this invite code';
COMMENT ON COLUMN public.profiles.invite_code_used IS 'The invite code this user used during registration';
