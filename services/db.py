from supabase import Client, create_client
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import uuid
from datetime import datetime

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing Supabase configuration in environment variables")

# Create Supabase service client (with elevated permissions)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


class DatabaseProduct(BaseModel):
    """
    Pydantic model for product data to be inserted into the database.
    
    Attributes:
        id: Unique identifier for the product
        type: Product category/type (e.g., "dress", "shoes", "accessory")
        search_query: Original search query used to find this product
        link: URL link to the product
        title: Product title/name
        price: Product price as string (to handle various formats)
        images: List of image URLs
        brand: Product brand name
        description: Product description
    """
    id: str
    type: str
    search_query: str
    link: str
    title: str
    price: float
    images: List[str]
    brand: str
    description: str
    color: str
    points: int


class DatabaseOutfit(BaseModel):
    """
    Pydantic model for outfit data to be inserted into the database.
    
    Attributes:
        title: Outfit name/title
        description: Outfit description
        image_url: URL to outfit image/preview
        user_prompt: Original user prompt that generated this outfit
    """
    title: str
    description: str
    image_url: Optional[str] = None
    user_prompt: str
    points: int


class DatabaseService:
    """
    Database service for handling CRUD operations on outfits and products.
    
    This service provides methods for:
    - Inserting outfits with their associated products
    - Creating relationships in the product_outfit_junction table
    - Managing database transactions for data consistency
    """

    def __init__(self):
        """Initialize the database service with Supabase client."""
        self.supabase = supabase

    def insert_outfit_with_products(
        self, 
        outfit: DatabaseOutfit, 
        products: List[DatabaseProduct]
    ) -> Dict[str, Any]:
        """
        Insert a new outfit along with its products and create the necessary relationships.
        
        This method performs the following operations in sequence:
        1. Insert each product into the products table (if not already exists)
        2. Insert the outfit into the outfits table
        3. Create relationships in the product_outfit_junction table
        
        Args:
            outfit: DatabaseOutfit model containing outfit information
            products: List of DatabaseProduct models to associate with the outfit
            
        Returns:
            Dict containing:
                - success: Boolean indicating operation success
                - outfit_id: ID of the created outfit
                - inserted_products: List of product IDs that were inserted
                - message: Success or error message
                
        Raises:
            Exception: If any database operation fails
        """
        try:
            # Step 1: Insert products (upsert to handle duplicates)
            inserted_products = []
            
            if products:
                print(f"📝 Inserting {len(products)} products...\n")
                
                for product in products:
                    try:
                        # Convert Pydantic model to dict for Supabase
                        product_data = product.model_dump(exclude_unset=True)
                        
                        # Use upsert to handle existing products gracefully
                        result = self.supabase.table("products").upsert(
                            product_data, 
                            on_conflict="id"
                        ).execute()
                        
                        if result.data:
                            inserted_products.append(product.id)
                            print(f"✅ Product inserted/updated: {product.title or product.id}")
                        
                    except Exception as e:
                        print(f"❌ Error inserting product {product.id}: {str(e)}")
                        # Continue with other products even if one fails
                        continue

            # Step 2: Insert the outfit
            print("📝 Inserting outfit...\n")
            outfit_data = outfit.model_dump(exclude_unset=True)
            
            outfit_result = self.supabase.table("outfits").insert(outfit_data).execute()
            
            if not outfit_result.data:
                raise Exception("Failed to insert outfit")
                
            outfit_id = outfit_result.data[0]["id"]
            print(f"✅ Outfit inserted with ID: {outfit_id}")

            # Step 3: Create relationships in product_outfit_junction
            if inserted_products:
                print(f"Creating {len(inserted_products)} product-outfit relationships...")
                
                junction_data = [
                    {
                        "outfit_id": outfit_id,
                        "product_id": product_id,
                        "created_at": datetime.utcnow().isoformat()
                    }
                    for product_id in inserted_products
                ]
                
                junction_result = self.supabase.table("product_outfit_junction").insert(
                    junction_data
                ).execute()
                
                if junction_result.data:
                    print(f"✅ Created {len(junction_result.data)} product-outfit relationships")

            return {
                "success": True,
                "outfit_id": outfit_id,
                "inserted_products": inserted_products,
                "message": f"Successfully created outfit with {len(inserted_products)} products"
            }

        except Exception as e:
            error_msg = f"Failed to insert outfit with products: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                "success": False,
                "outfit_id": None,
                "inserted_products": [],
                "message": error_msg
            }

    def get_outfit_with_products(self, outfit_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve an outfit along with all its associated products.
        
        Args:
            outfit_id: ID of the outfit to retrieve
            
        Returns:
            Dict containing outfit data and associated products, or None if not found
        """
        try:
            # Get outfit data
            outfit_result = self.supabase.table("outfits").select("*").eq("id", outfit_id).execute()
            
            if not outfit_result.data:
                return None
                
            outfit = outfit_result.data[0]

            # Get associated products through junction table
            products_result = self.supabase.table("product_outfit_junction").select(
                """
                products (
                    id,
                    title,
                    description,
                    type,
                    brand,
                    price,
                    images,
                    link,
                    search_query
                )
                """
            ).eq("outfit_id", outfit_id).execute()
            
            # Extract product data from junction results
            products = []
            if products_result.data:
                products = [item["products"] for item in products_result.data if item["products"]]

            return {
                "outfit": outfit,
                "products": products
            }

        except Exception as e:
            print(f"Error retrieving outfit {outfit_id}: {str(e)}")
            return None

    def delete_outfit(self, outfit_id: int) -> Dict[str, Any]:
        """
        Delete an outfit and all its associated relationships.
        
        Note: Products are not deleted as they might be used in other outfits.
        Only the outfit and its relationships are removed.
        
        Args:
            outfit_id: ID of the outfit to delete
            
        Returns:
            Dict with success status and message
        """
        try:
            # Delete the outfit (cascade will handle junction table)
            result = self.supabase.table("outfits").delete().eq("id", outfit_id).execute()
            
            if result.data:
                return {
                    "success": True,
                    "message": f"Successfully deleted outfit {outfit_id}"
                }
            else:
                return {
                    "success": False,
                    "message": f"Outfit {outfit_id} not found"
                }

        except Exception as e:
            error_msg = f"Failed to delete outfit {outfit_id}: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                "success": False,
                "message": error_msg
            }

    def get_user_liked_outfits(
        self, 
        user_id: str, 
        page: int = 1, 
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        Retrieve all outfits that a user has liked with pagination.
        
        Args:
            user_id: ID of the user whose liked outfits to retrieve
            page: Page number (starting from 1)
            page_size: Number of outfits per page
            
        Returns:
            Dict containing:
                - outfits: List of liked outfit data with products
                - total_count: Total number of liked outfits
                - page: Current page number
                - page_size: Number of items per page
        """
        try:
            # Calculate offset for pagination
            offset = (page - 1) * page_size
            
            # Get liked outfits with pagination through junction table
            likes_result = self.supabase.table("user_outfit_likes").select(
                """
                outfit_id,
                created_at,
                outfits (
                    id,
                    title,
                    description,
                    image_url,
                    user_prompt,
                    created_at
                )
                """
            ).eq("user_id", user_id).order("created_at", desc=True).range(
                offset, offset + page_size - 1
            ).execute()
            
            # Get total count for pagination
            count_result = self.supabase.table("user_outfit_likes").select(
                "outfit_id", count="exact"
            ).eq("user_id", user_id).execute()
            
            total_count = count_result.count if count_result.count else 0
            
            # Process the results to get complete outfit data with products
            outfits = []
            for like_record in likes_result.data:
                if like_record.get("outfits"):
                    outfit_id = like_record["outfits"]["id"]
                    
                    # Get associated products for each outfit
                    outfit_with_products = self.get_outfit_with_products(outfit_id)
                    if outfit_with_products:
                        outfit_data = outfit_with_products["outfit"]
                        products = outfit_with_products["products"]
                        
                        # Add the products to the outfit data
                        outfit_data["products"] = products
                        outfits.append(outfit_data)
            
            return {
                "outfits": outfits,
                "total_count": total_count,
                "page": page,
                "page_size": page_size
            }
            
        except Exception as e:
            error_msg = f"Failed to retrieve user liked outfits: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                "outfits": [],
                "total_count": 0,
                "page": page,
                "page_size": page_size
            }

    def like_outfit(self, user_id: str, outfit_id: int) -> Dict[str, Any]:
        """
        Like an outfit for a user by managing both likes and dislikes tables.
        
        This method performs the following operations:
        1. Remove any existing dislike for this user/outfit combination
        2. Add a like entry (using upsert to handle duplicate likes gracefully)
        
        Args:
            user_id: ID of the user liking the outfit
            outfit_id: ID of the outfit being liked
            
        Returns:
            Dict containing:
                - success: Boolean indicating operation success
                - message: Success or error message
                
        Raises:
            Exception: If database operations fail
        """
        try:
            # Step 1: Remove from dislikes table if exists
            dislike_result = self.supabase.table("user_outfit_dislikes").delete().eq(
                "user_id", user_id
            ).eq("outfit_id", outfit_id).execute()
            
            if dislike_result.data:
                print(f"✅ Removed existing dislike for user {user_id}, outfit {outfit_id}")
            
            # Step 2: Add to likes table (upsert to handle duplicates)
            like_data = {
                "user_id": user_id,
                "outfit_id": outfit_id,
                "created_at": datetime.utcnow().isoformat()
            }
            
            like_result = self.supabase.table("user_outfit_likes").upsert(
                like_data,
                on_conflict="user_id,outfit_id"
            ).execute()
            
            if like_result.data:
                return {
                    "success": True,
                    "message": f"Successfully liked outfit {outfit_id}"
                }
            else:
                raise Exception("Failed to insert like record")
                
        except Exception as e:
            error_msg = f"Failed to like outfit {outfit_id} for user {user_id}: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                "success": False,
                "message": error_msg
            }

    def dislike_outfit(self, user_id: str, outfit_id: int) -> Dict[str, Any]:
        """
        Dislike an outfit for a user by managing both likes and dislikes tables.
        
        This method performs the following operations:
        1. Remove any existing like for this user/outfit combination
        2. Add a dislike entry (using upsert to handle duplicate dislikes gracefully)
        
        Args:
            user_id: ID of the user disliking the outfit
            outfit_id: ID of the outfit being unliked
            
        Returns:
            Dict containing:
                - success: Boolean indicating operation success
                - message: Success or error message
                
        Raises:
            Exception: If database operations fail
        """
        try:
            # Step 1: Remove from likes table if exists
            like_result = self.supabase.table("user_outfit_likes").delete().eq(
                "user_id", user_id
            ).eq("outfit_id", outfit_id).execute()
            
            if like_result.data:
                print(f"✅ Removed existing like for user {user_id}, outfit {outfit_id}")
            
            # Step 2: Add to dislikes table (upsert to handle duplicates)
            dislike_data = {
                "user_id": user_id,
                "outfit_id": outfit_id,
                "created_at": datetime.utcnow().isoformat()
            }
            
            dislike_result = self.supabase.table("user_outfit_dislikes").upsert(
                dislike_data,
                on_conflict="user_id,outfit_id"
            ).execute()
            
            if dislike_result.data:
                return {
                    "success": True,
                    "message": f"Successfully unliked outfit {outfit_id}"
                }
            else:
                raise Exception("Failed to insert dislike record")
                
        except Exception as e:
            error_msg = f"Failed to unlike outfit {outfit_id} for user {user_id}: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                "success": False,
                "message": error_msg
            }

# Create a singleton instance for use across the application
db_service = DatabaseService()

def get_database_service() -> DatabaseService:
    """
    Dependency function to get the database service instance.
    Use this in FastAPI route dependencies.
    
    Returns:
        DatabaseService: Singleton database service instance
    """
    return db_service