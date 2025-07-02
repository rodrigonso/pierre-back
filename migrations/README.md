# Database Migrations

This directory contains SQL migration files for the Pierre fashion platform database.

## Migration Files

### 001_initial_schema.sql
Initial database schema setup that creates all core tables for the Pierre platform:

- **profiles**: User profiles linked to Supabase Auth
- **products**: Product catalog from various shopping sources  
- **outfits**: Generated outfit concepts
- **product_outfit_junction**: Links products to outfits
- **user_outfit_likes**: User likes for outfits
- **user_outfit_dislikes**: User dislikes for outfits
- **user_product_likes**: User likes for individual products

## How to Apply Migrations

### Option 1: Supabase Dashboard (Recommended)
1. Open your Supabase project dashboard
2. Go to the SQL Editor
3. Copy and paste the content of `001_initial_schema.sql`
4. Click "Run" to execute the migration

### Option 2: Supabase CLI
```bash
# Install Supabase CLI if you haven't already
npm install -g supabase

# Login to Supabase
supabase login

# Link your project (replace with your project reference)
supabase link --project-ref your-project-ref

# Apply the migration
supabase db push
```

### Option 3: Direct PostgreSQL Connection
If you have direct access to your PostgreSQL database:
```bash
psql "postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres" -f migrations/001_initial_schema.sql
```

## Security Features

The migration includes comprehensive Row Level Security (RLS) policies:

- **User Data Protection**: Users can only access their own profiles, likes, and saved outfits
- **Public Content**: Products and outfits are readable by all authenticated users
- **Service Operations**: Backend operations use service role for data management
- **Cascading Deletes**: Proper cleanup when users or content is deleted

## Performance Optimizations

The migration includes indexes for:
- Timestamp-based queries (created_at fields)
- Product filtering (type, source)
- User-specific lookups (user_id foreign keys)

## Database Relationships

```
auth.users (Supabase Auth)
    ↓ (1:1)
profiles
    ↓ (1:many)
outfits → product_outfit_junction
    ↓                      ↓              ↓
user_outfit_likes     user_outfit_dislikes   products
    ↓                                        ↓
user_product_likes ←------------------------/
```

## Environment Variables Required

Make sure your `.env` file has these Supabase variables set:
```env
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_key
```

## After Migration

Once the migration is applied, your Pierre backend will be able to:
- Store user profiles and preferences
- Manage product catalogs from shopping APIs
- Generate and store outfit concepts
- Track user interactions (likes, saves, dislikes)
- Implement proper security and access controls
