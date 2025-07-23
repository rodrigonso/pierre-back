-- Pierre Fashion Platform - Collections Feature Migration
-- Migration: 004_collections
-- Created: 2025-07-19
-- Description: Creates collections tables to allow users to organize their liked products and outfits

-- ============================================================================
-- COLLECTIONS TABLE
-- ============================================================================
-- User collections for organizing liked products and outfits
CREATE TABLE IF NOT EXISTS public.collections (
    id uuid NOT NULL DEFAULT uuid_generate_v4(),
    user_id uuid NOT NULL,
    name text NOT NULL,
    description text NULL,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    
    CONSTRAINT collections_pkey PRIMARY KEY (id),
    CONSTRAINT collections_user_id_fkey FOREIGN KEY (user_id) 
        REFERENCES auth.users (id) ON DELETE CASCADE,
    CONSTRAINT collections_name_check CHECK (length(name) >= 1 AND length(name) <= 100)
) TABLESPACE pg_default;

-- ============================================================================
-- COLLECTION ITEMS TABLE
-- ============================================================================
-- Items within collections (products or outfits)
CREATE TABLE IF NOT EXISTS public.collection_items (
    id uuid NOT NULL DEFAULT uuid_generate_v4(),
    collection_id uuid NOT NULL,
    item_type text NOT NULL CHECK (item_type IN ('product', 'outfit')),
    item_id text NOT NULL,
    added_at timestamp with time zone NOT NULL DEFAULT now(),
    
    CONSTRAINT collection_items_pkey PRIMARY KEY (id),
    CONSTRAINT collection_items_collection_id_fkey FOREIGN KEY (collection_id) 
        REFERENCES public.collections (id) ON DELETE CASCADE,
    -- Unique constraint to prevent duplicate items in the same collection
    CONSTRAINT collection_items_unique_item UNIQUE (collection_id, item_type, item_id)
) TABLESPACE pg_default;

-- ============================================================================
-- INDEXES
-- ============================================================================
-- Index for efficient user collection queries
CREATE INDEX IF NOT EXISTS idx_collections_user_id ON public.collections(user_id);

-- Index for efficient collection item queries
CREATE INDEX IF NOT EXISTS idx_collection_items_collection_id ON public.collection_items(collection_id);

-- Index for efficient item type queries
CREATE INDEX IF NOT EXISTS idx_collection_items_type_id ON public.collection_items(item_type, item_id);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================
-- Enable RLS on collections table
ALTER TABLE public.collections ENABLE ROW LEVEL SECURITY;

-- Users can only see and manage their own collections
CREATE POLICY "Users can view their own collections" ON public.collections
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own collections" ON public.collections
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own collections" ON public.collections
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own collections" ON public.collections
    FOR DELETE USING (auth.uid() = user_id);

-- Enable RLS on collection_items table
ALTER TABLE public.collection_items ENABLE ROW LEVEL SECURITY;

-- Users can only manage items in their own collections
CREATE POLICY "Users can view items in their own collections" ON public.collection_items
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.collections 
            WHERE collections.id = collection_items.collection_id 
            AND collections.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert items into their own collections" ON public.collection_items
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.collections 
            WHERE collections.id = collection_items.collection_id 
            AND collections.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can delete items from their own collections" ON public.collection_items
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM public.collections 
            WHERE collections.id = collection_items.collection_id 
            AND collections.user_id = auth.uid()
        )
    );

-- ============================================================================
-- FUNCTIONS
-- ============================================================================
-- Function to update the updated_at timestamp on collections
CREATE OR REPLACE FUNCTION update_collections_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to automatically update updated_at on collections
CREATE TRIGGER update_collections_updated_at_trigger
    BEFORE UPDATE ON public.collections
    FOR EACH ROW
    EXECUTE FUNCTION update_collections_updated_at();

-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE public.collections IS 'User collections for organizing liked products and outfits';
COMMENT ON COLUMN public.collections.id IS 'Unique identifier for the collection';
COMMENT ON COLUMN public.collections.user_id IS 'ID of the user who owns the collection';
COMMENT ON COLUMN public.collections.name IS 'User-defined name for the collection (1-100 characters)';
COMMENT ON COLUMN public.collections.description IS 'Optional description for the collection';
COMMENT ON COLUMN public.collections.created_at IS 'Timestamp when the collection was created';
COMMENT ON COLUMN public.collections.updated_at IS 'Timestamp when the collection was last updated';

COMMENT ON TABLE public.collection_items IS 'Items within user collections';
COMMENT ON COLUMN public.collection_items.id IS 'Unique identifier for the collection item';
COMMENT ON COLUMN public.collection_items.collection_id IS 'ID of the collection this item belongs to';
COMMENT ON COLUMN public.collection_items.item_type IS 'Type of item: product or outfit';
COMMENT ON COLUMN public.collection_items.item_id IS 'ID of the product or outfit';
COMMENT ON COLUMN public.collection_items.added_at IS 'Timestamp when the item was added to the collection';
