from supabase import create_client, Client
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
import os
from datetime import datetime
from pydantic import BaseModel
from utils.models import Product, Outfit
import uuid
import json

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing Supabase configuration in environment variables")

# Database-specific Pydantic models
class DbProduct(BaseModel):
    """Pydantic model for product database operations"""
    id: str
    type: Optional[str] = None
    search_query: Optional[str] = None
    link: Optional[str] = None
    title: Optional[str] = None
    price: Optional[str] = None  # Stored as string to handle various formats
    images: Optional[List[str]] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None

class DbOutfit(BaseModel):
    """Pydantic model for outfit database operations"""
    id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    user_prompt: Optional[str] = None
    created_at: Optional[datetime] = None

class DbProductOutfitJunction(BaseModel):
    """Pydantic model for product-outfit relationship"""
    outfit_id: int
    product_id: str
    created_at: Optional[datetime] = None

class DbService:
    """
    Database service for handling operations with Supabase database.
    Provides methods for managing outfits, products, and their relationships.
    """
    
    def __init__(self):
        """Initialize the DbService with Supabase client using service role."""
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    # ============================================================================
    # PRODUCT OPERATIONS
    # ============================================================================
    
    async def create_product(self, product: Product) -> Optional[DbProduct]:
        """
        Create a new product in the database.
        
        Args:
            product: Product object to create
            
        Returns:
            DbProduct: Created product or None if failed
            
        Raises:
            Exception: If database operation fails
        """
        try:
            # Convert Product to database format
            product_data = {
                "id": product.id,
                "type": product.type,
                "search_query": product.query,
                "link": product.link,
                "title": product.title,
                "price": str(product.price) if product.price else None,
                "images": product.images or [],
                "brand": getattr(product, 'brand', None),  # Some Product objects might not have brand
                "description": product.description,
                "created_at": datetime.utcnow().isoformat()
            }
            
            response = self.client.table("products").insert(product_data).execute()
            
            if response.data:
                return DbProduct(**response.data[0])
            return None
            
        except Exception as e:
            print(f"Error creating product: {e}")
            raise Exception(f"Failed to create product: {str(e)}")
    
    async def get_product_by_id(self, product_id: str) -> Optional[DbProduct]:
        """
        Get a product by its ID.
        
        Args:
            product_id: Unique identifier for the product
            
        Returns:
            DbProduct: Product data or None if not found
        """
        try:
            response = self.client.table("products").select("*").eq("id", product_id).execute()
            
            if response.data:
                return DbProduct(**response.data[0])
            return None
            
        except Exception as e:
            print(f"Error getting product: {e}")
            return None
    
    async def get_products_by_type(self, product_type: str, limit: int = 50) -> List[DbProduct]:
        """
        Get products filtered by type.
        
        Args:
            product_type: Type of products to retrieve
            limit: Maximum number of products to return
            
        Returns:
            List[DbProduct]: List of products matching the type
        """
        try:
            response = self.client.table("products").select("*").eq("type", product_type).limit(limit).execute()
            
            return [DbProduct(**item) for item in response.data]
            
        except Exception as e:
            print(f"Error getting products by type: {e}")
            return []
    
    async def get_products_by_brand(self, brand: str, limit: int = 50) -> List[DbProduct]:
        """
        Get products filtered by brand.
        
        Args:
            brand: Brand name to filter by
            limit: Maximum number of products to return
            
        Returns:
            List[DbProduct]: List of products from the specified brand
        """
        try:
            response = self.client.table("products").select("*").eq("brand", brand).limit(limit).execute()
            
            return [DbProduct(**item) for item in response.data]
            
        except Exception as e:
            print(f"Error getting products by brand: {e}")
            return []
    
    async def search_products(self, search_term: str, limit: int = 20) -> List[DbProduct]:
        """
        Search products by title or description.
        
        Args:
            search_term: Term to search for in product title/description
            limit: Maximum number of products to return
            
        Returns:
            List[DbProduct]: List of products matching the search term
        """
        try:
            # Use ilike for case-insensitive search
            response = self.client.table("products").select("*").or_(
                f"title.ilike.%{search_term}%,description.ilike.%{search_term}%"
            ).limit(limit).execute()
            
            return [DbProduct(**item) for item in response.data]
            
        except Exception as e:
            print(f"Error searching products: {e}")
            return []
    
    async def update_product(self, product_id: str, updates: Dict[str, Any]) -> Optional[DbProduct]:
        """
        Update a product with new data.
        
        Args:
            product_id: ID of the product to update
            updates: Dictionary of fields to update
            
        Returns:
            DbProduct: Updated product or None if failed
        """
        try:
            response = self.client.table("products").update(updates).eq("id", product_id).execute()
            
            if response.data:
                return DbProduct(**response.data[0])
            return None
            
        except Exception as e:
            print(f"Error updating product: {e}")
            return None
    
    async def delete_product(self, product_id: str) -> bool:
        """
        Delete a product from the database.
        
        Args:
            product_id: ID of the product to delete
            
        Returns:
            bool: True if deleted successfully, False otherwise
        """
        try:
            response = self.client.table("products").delete().eq("id", product_id).execute()
            return len(response.data) > 0
            
        except Exception as e:
            print(f"Error deleting product: {e}")
            return False
    
    # ============================================================================
    # OUTFIT OPERATIONS
    # ============================================================================
    
    async def create_outfit(self, outfit: Outfit, user_prompt: Optional[str] = None) -> Optional[DbOutfit]:
        """
        Create a new outfit in the database.
        
        Args:
            outfit: Outfit object to create
            user_prompt: Optional user prompt that generated this outfit
            
        Returns:
            DbOutfit: Created outfit or None if failed
            
        Raises:
            Exception: If database operation fails
        """
        try:
            outfit_data = {
                "title": outfit.name,
                "description": outfit.description,
                "image_url": outfit.image_url,
                "user_prompt": user_prompt,
                "created_at": datetime.utcnow().isoformat()
            }
            
            response = self.client.table("outfits").insert(outfit_data).execute()
            
            if response.data:
                return DbOutfit(**response.data[0])
            return None
            
        except Exception as e:
            print(f"Error creating outfit: {e}")
            raise Exception(f"Failed to create outfit: {str(e)}")
    
    async def get_outfit_by_id(self, outfit_id: int) -> Optional[DbOutfit]:
        """
        Get an outfit by its ID.
        
        Args:
            outfit_id: Unique identifier for the outfit
            
        Returns:
            DbOutfit: Outfit data or None if not found
        """
        try:
            response = self.client.table("outfits").select("*").eq("id", outfit_id).execute()
            
            if response.data:
                return DbOutfit(**response.data[0])
            return None
            
        except Exception as e:
            print(f"Error getting outfit: {e}")
            return None
    
    async def get_all_outfits(self, limit: int = 50, offset: int = 0) -> List[DbOutfit]:
        """
        Get all outfits with pagination.
        
        Args:
            limit: Maximum number of outfits to return
            offset: Number of outfits to skip
            
        Returns:
            List[DbOutfit]: List of outfits
        """
        try:
            response = self.client.table("outfits").select("*").range(offset, offset + limit - 1).order("created_at", desc=True).execute()
            
            return [DbOutfit(**item) for item in response.data]
            
        except Exception as e:
            print(f"Error getting outfits: {e}")
            return []
    
    async def search_outfits(self, search_term: str, limit: int = 20) -> List[DbOutfit]:
        """
        Search outfits by title, description, or user prompt.
        
        Args:
            search_term: Term to search for
            limit: Maximum number of outfits to return
            
        Returns:
            List[DbOutfit]: List of outfits matching the search term
        """
        try:
            response = self.client.table("outfits").select("*").or_(
                f"title.ilike.%{search_term}%,description.ilike.%{search_term}%,user_prompt.ilike.%{search_term}%"
            ).limit(limit).execute()
            
            return [DbOutfit(**item) for item in response.data]
            
        except Exception as e:
            print(f"Error searching outfits: {e}")
            return []
    
    async def update_outfit(self, outfit_id: int, updates: Dict[str, Any]) -> Optional[DbOutfit]:
        """
        Update an outfit with new data.
        
        Args:
            outfit_id: ID of the outfit to update
            updates: Dictionary of fields to update
            
        Returns:
            DbOutfit: Updated outfit or None if failed
        """
        try:
            response = self.client.table("outfits").update(updates).eq("id", outfit_id).execute()
            
            if response.data:
                return DbOutfit(**response.data[0])
            return None
            
        except Exception as e:
            print(f"Error updating outfit: {e}")
            return None
    
    async def delete_outfit(self, outfit_id: int) -> bool:
        """
        Delete an outfit from the database.
        
        Args:
            outfit_id: ID of the outfit to delete
            
        Returns:
            bool: True if deleted successfully, False otherwise
        """
        try:
            response = self.client.table("outfits").delete().eq("id", outfit_id).execute()
            return len(response.data) > 0
            
        except Exception as e:
            print(f"Error deleting outfit: {e}")
            return False
    
    # ============================================================================
    # PRODUCT-OUTFIT RELATIONSHIP OPERATIONS
    # ============================================================================
    
    async def add_product_to_outfit(self, outfit_id: int, product_id: str) -> Optional[DbProductOutfitJunction]:
        """
        Add a product to an outfit.
        
        Args:
            outfit_id: ID of the outfit
            product_id: ID of the product to add
            
        Returns:
            DbProductOutfitJunction: Created relationship or None if failed
            
        Raises:
            Exception: If database operation fails
        """
        try:
            junction_data = {
                "outfit_id": outfit_id,
                "product_id": product_id,
                "created_at": datetime.utcnow().isoformat()
            }
            
            response = self.client.table("product_outfit_junction").insert(junction_data).execute()
            
            if response.data:
                return DbProductOutfitJunction(**response.data[0])
            return None
            
        except Exception as e:
            print(f"Error adding product to outfit: {e}")
            raise Exception(f"Failed to add product to outfit: {str(e)}")
    
    async def remove_product_from_outfit(self, outfit_id: int, product_id: str) -> bool:
        """
        Remove a product from an outfit.
        
        Args:
            outfit_id: ID of the outfit
            product_id: ID of the product to remove
            
        Returns:
            bool: True if removed successfully, False otherwise
        """
        try:
            response = self.client.table("product_outfit_junction").delete().eq(
                "outfit_id", outfit_id
            ).eq("product_id", product_id).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            print(f"Error removing product from outfit: {e}")
            return False
    
    async def get_outfit_products(self, outfit_id: int) -> List[DbProduct]:
        """
        Get all products associated with an outfit.
        
        Args:
            outfit_id: ID of the outfit
            
        Returns:
            List[DbProduct]: List of products in the outfit
        """
        try:
            # Join query to get products for a specific outfit
            response = self.client.table("product_outfit_junction").select(
                "product_id, products(*)"
            ).eq("outfit_id", outfit_id).execute()
            
            products = []
            for item in response.data:
                if item.get("products"):
                    products.append(DbProduct(**item["products"]))
            
            return products
            
        except Exception as e:
            print(f"Error getting outfit products: {e}")
            return []
    
    async def get_product_outfits(self, product_id: str) -> List[DbOutfit]:
        """
        Get all outfits that contain a specific product.
        
        Args:
            product_id: ID of the product
            
        Returns:
            List[DbOutfit]: List of outfits containing the product
        """
        try:
            # Join query to get outfits for a specific product
            response = self.client.table("product_outfit_junction").select(
                "outfit_id, outfits(*)"
            ).eq("product_id", product_id).execute()
            
            outfits = []
            for item in response.data:
                if item.get("outfits"):
                    outfits.append(DbOutfit(**item["outfits"]))
            
            return outfits
            
        except Exception as e:
            print(f"Error getting product outfits: {e}")
            return []
    
    # ============================================================================
    # BULK OPERATIONS
    # ============================================================================
    
    async def create_outfit_with_products(self, outfit: Outfit, products: List[Product], user_prompt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create an outfit and associate it with products in a single transaction-like operation.
        
        Args:
            outfit: Outfit object to create
            products: List of products to associate with the outfit
            user_prompt: Optional user prompt that generated this outfit
            
        Returns:
            Dict containing created outfit and product relationships, or None if failed
            
        Raises:
            Exception: If any part of the operation fails
        """
        try:
            # First, create the outfit
            db_outfit = await self.create_outfit(outfit, user_prompt)
            if not db_outfit:
                raise Exception("Failed to create outfit")
            
            # Then, create products that don't exist and collect their IDs
            product_ids = []
            created_products = []
            
            for product in products:
                # Check if product already exists
                existing_product = await self.get_product_by_id(product.id)
                if existing_product:
                    product_ids.append(product.id)
                else:
                    # Create new product
                    new_product = await self.create_product(product)
                    if new_product:
                        product_ids.append(new_product.id)
                        created_products.append(new_product)
                    else:
                        print(f"Warning: Failed to create product {product.id}")
            
            # Finally, create the relationships
            relationships = []
            for product_id in product_ids:
                relationship = await self.add_product_to_outfit(db_outfit.id, product_id)
                if relationship:
                    relationships.append(relationship)
            
            return {
                "outfit": db_outfit,
                "created_products": created_products,
                "relationships": relationships,
                "total_products": len(product_ids)
            }
            
        except Exception as e:
            print(f"Error creating outfit with products: {e}")
            raise Exception(f"Failed to create outfit with products: {str(e)}")
    
    async def get_outfit_complete(self, outfit_id: int) -> Optional[Dict[str, Any]]:
        """
        Get complete outfit information including all associated products.
        
        Args:
            outfit_id: ID of the outfit
            
        Returns:
            Dict containing outfit and its products, or None if not found
        """
        try:
            # Get the outfit
            outfit = await self.get_outfit_by_id(outfit_id)
            if not outfit:
                return None
            
            # Get associated products
            products = await self.get_outfit_products(outfit_id)
            
            return {
                "outfit": outfit,
                "products": products,
                "product_count": len(products)
            }
            
        except Exception as e:
            print(f"Error getting complete outfit: {e}")
            return None
    
    # ============================================================================
    # UTILITY METHODS
    # ============================================================================
    
    async def get_database_stats(self) -> Dict[str, int]:
        """
        Get basic statistics about the database.
        
        Returns:
            Dict containing counts of outfits, products, and relationships
        """
        try:
            stats = {}
            
            # Count outfits
            outfit_response = self.client.table("outfits").select("id", count="exact").execute()
            stats["total_outfits"] = outfit_response.count or 0
            
            # Count products
            product_response = self.client.table("products").select("id", count="exact").execute()
            stats["total_products"] = product_response.count or 0
            
            # Count relationships
            junction_response = self.client.table("product_outfit_junction").select("outfit_id", count="exact").execute()
            stats["total_relationships"] = junction_response.count or 0
            
            return stats
            
        except Exception as e:
            print(f"Error getting database stats: {e}")
            return {"total_outfits": 0, "total_products": 0, "total_relationships": 0}
