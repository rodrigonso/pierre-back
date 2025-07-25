from supabase import Client, create_client, acreate_client
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import uuid
import re
from datetime import datetime
import numpy as np
from openai import OpenAI
from services.logger import get_logger_service
from typing import TypeVar, Generic

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing Supabase configuration in environment variables")

logger_service = get_logger_service()

T = TypeVar('T')
class DatabasePaginatedResponse(BaseModel, Generic[T]):
    total_count: int
    page: int
    page_size: int
    success: bool
    data: List[T]

class DatabaseSimilarityResponse(BaseModel, Generic[T]):
    success: bool
    message: str
    data: List[T]
    target: T

class DatabaseLikeResponse(BaseModel):
    success: bool
    message: str
    is_liked: bool

class DatabaseProduct(BaseModel):
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
    style: str
    is_liked: Optional[bool] = None

class DatabaseOutfit(BaseModel):
    id: Optional[int] = None
    name: str
    description: str
    image_url: Optional[str] = None
    user_prompt: str
    style: str
    points: int
    is_liked: Optional[bool] = None
    products: Optional[List[DatabaseProduct]] = None

class DatabaseService:
    """
    Database service for handling CRUD operations on outfits and products.
    
    This service provides methods for:
    - Inserting outfits with their associated products
    - Creating relationships in the product_outfit_junction table
    - Managing database transactions for data consistency
    - Finding similar outfits using semantic similarity
    """

    def __init__(self):
        """Initialize the database service with Supabase client and OpenAI client."""
        # Initialize OpenAI client for embeddings
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def initialize_client(self):
        """
        Initialize the Supabase client asynchronously.
        
        This method is necessary to ensure the Supabase client is created
        with elevated permissions for CRUD operations.
        """
        self.supabase: Client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# === OUTFITS CRUD OPERATIONS ===
    async def get_outfit(self, outfit_id: int, user_id: str = None, include_likes: bool = False) -> Optional[DatabaseOutfit]:
        """
        Retrieve an outfit without its associated products.
        
        Args:
            outfit_id: ID of the outfit to retrieve
            
        Returns:
            DatabaseOutfit object if found, or None if not found
        """
        try:
            # Get outfit data without products
            outfit_result = await self.supabase.table("outfits").select("*").eq("id", outfit_id).execute()
            
            if not outfit_result.data:
                return None
            
            outfit_data = outfit_result.data[0]
            
            # Convert raw data to DatabaseOutfit object
            outfit_obj = DatabaseOutfit(**outfit_data)
            
            return outfit_obj

        except Exception as e:
            logger_service.error(f"Failed to retrieve outfit {outfit_id}: {str(e)}")
            return None

    async def get_outfit_with_products(self, outfit_id: int, user_id: str = None, include_likes: bool = False) -> Optional[DatabaseOutfit]:
        """
        Retrieve an outfit along with all its associated products.
        
        Args:
            outfit_id: ID of the outfit to retrieve
            
        Returns:
            Dict containing outfit data and associated products, or None if not found
        """
        try:
            if include_likes:
                outfit_result = await self.supabase.table("outfits").select(
                    "*, user_outfit_likes!left(outfit_id)"
                ).eq("id", outfit_id).execute()
            else:
                outfit_result = await self.supabase.table("outfits").select("*").eq("id", outfit_id).execute()

            if not outfit_result.data:
                return None

            outfit = outfit_result.data[0]
            products = await self._get_outfit_products(outfit_id)

            if include_likes and user_id:
                outfit['is_liked'] = len(outfit.get("user_outfit_likes", [])) == 1
            else:
                outfit['is_liked'] = None

            return DatabaseOutfit(**outfit, products=products)

        except Exception as e:
            logger_service.error(f"Failed to retrieve outfit {outfit_id}: {str(e)}")
            return None

    async def get_outfits(self, page: int = 1, page_size: int = 10, user_id: str = None, include_likes: bool = False, style: Optional[str] = None) -> DatabasePaginatedResponse[DatabaseOutfit]:
        """
        Retrieve a paginated list of outfits from the database.
        
        Args:
            page: Page number for pagination (default is 1)
            page_size: Number of outfits to return per page (default is 10)
            user_id: User ID for like status (optional)
            include_likes: Whether to include like status for the user
            style: Filter outfits by style (optional)
            
        Returns:
            DatabasePaginatedResponse containing DatabaseOutfit objects with pagination applied
        """
        try:
            offset = (page - 1) * page_size

            # Build the base query
            if include_likes and user_id:
                query = self.supabase.table("outfits").select("*, user_outfit_likes!left(outfit_id)").eq("user_outfit_likes.user_id", user_id)
            else:
                query = self.supabase.table("outfits").select("*")
            
            # Apply style filter if provided (supports comma-separated values with OR logic)
            if style:
                style_values = [s.strip().lower() for s in style.split(',') if s.strip()]
                if len(style_values) == 1:
                    # Single value - use simple ilike for case-insensitive matching
                    query = query.ilike("style", f"%{style_values[0]}%")
                elif len(style_values) > 1:
                    # Multiple values - use OR logic
                    style_conditions = ",".join([f'style.ilike.%{style_val}%' for style_val in style_values])
                    query = query.or_(style_conditions)
            
            # Execute query with pagination and ordering
            outfits = await query.order("created_at", desc=True).range(offset, offset + page_size - 1).execute()

            # Get total count with same filters applied
            count_query = self.supabase.table("outfits").select("id", count="exact")
            if style:
                style_values = [s.strip().lower() for s in style.split(',') if s.strip()]
                if len(style_values) == 1:
                    # Single value - use simple ilike for case-insensitive matching
                    count_query = count_query.ilike("style", f"%{style_values[0]}%")
                elif len(style_values) > 1:
                    # Multiple values - use OR logic
                    style_conditions = ",".join([f'style.ilike.%{style_val}%' for style_val in style_values])
                    count_query = count_query.or_(style_conditions)
            
            count_result = await count_query.execute()
            total_count = count_result.count if count_result.count else 0

            # Convert raw outfit data to DatabaseOutfit objects
            outfit_objects = []
            for outfit_data in outfits.data:
                try:

                    if include_likes and user_id:
                        outfit_data['is_liked'] = len(outfit_data.get("user_outfit_likes", [])) == 1
                    else:
                        outfit_data['is_liked'] = None

                    outfit_obj = DatabaseOutfit(**outfit_data)
                    outfit_objects.append(outfit_obj)

                except Exception as e:
                    logger_service.error(f"Failed to convert outfit {outfit_data.get('id')} to DatabaseOutfit: {str(e)}")
                    # Continue processing other outfits instead of failing entirely
                    continue
            print(outfit_objects)

            return DatabasePaginatedResponse[DatabaseOutfit](
                data=outfit_objects,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )
        except Exception as e:
            logger_service.error(f"Failed to retrieve outfits: {str(e)}")
            return DatabasePaginatedResponse[DatabaseOutfit](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

    async def get_outfits_with_products(self, page: int = 1, page_size: int = 10, user_id: str = None, include_likes: bool = False, style: Optional[str] = None) -> DatabasePaginatedResponse[DatabaseOutfit]:
        """
        Retrieve all outfits along with their associated products with pagination.

        Args:
            page: Page number (starting from 1)
            page_size: Number of outfits per page
            user_id: User ID for like status (optional)
            include_likes: Whether to include like status for the user
            style: Filter outfits by style (optional)

        Returns:
            DatabasePaginatedResponse containing:
                - data: List of DatabaseOutfit objects
                - total_count: Total number of outfits
                - page: Current page number
                - page_size: Number of outfits per page
        """
        try:
            offset = (page - 1) * page_size
            
            # Build the base query
            if include_likes and user_id:
                query = self.supabase.table("outfits").select(
                    "*, user_outfit_likes!left(outfit_id)"
                ).eq("user_outfit_likes.user_id", user_id)
            else:
                query = self.supabase.table("outfits").select("*")
            
            # Apply style filter if provided (supports comma-separated values with OR logic)
            if style:
                style_values = [s.strip().lower() for s in style.split(',') if s.strip()]
                if len(style_values) == 1:
                    # Single value - use simple ilike for case-insensitive matching
                    query = query.ilike("style", f"%{style_values[0]}%")
                elif len(style_values) > 1:
                    # Multiple values - use OR logic
                    style_conditions = ",".join([f'style.ilike.%{style_val}%' for style_val in style_values])
                    query = query.or_(style_conditions)
            
            # Execute query with pagination
            outfits = await query.range(offset, offset + page_size - 1).execute()

            if not outfits.data:
                return DatabasePaginatedResponse[DatabaseOutfit](
                    data=[],
                    total_count=0,
                    page=page,
                    page_size=page_size,
                    success=True
                )
            
            # Get total count with same filters applied
            count_query = self.supabase.table("outfits").select("id", count="exact")
            if style:
                style_values = [s.strip().lower() for s in style.split(',') if s.strip()]
                if len(style_values) == 1:
                    # Single value - use simple ilike for case-insensitive matching
                    count_query = count_query.ilike("style", f"%{style_values[0]}%")
                elif len(style_values) > 1:
                    # Multiple values - use OR logic
                    style_conditions = ",".join([f'style.ilike.%{style_val}%' for style_val in style_values])
                    count_query = count_query.or_(style_conditions)
            
            count_result = await count_query.execute()
            total_count = count_result.count if count_result.count else 0
            
            # Convert raw outfit data to DatabaseOutfit objects
            outfit_objects: List[DatabaseOutfit] = []
            for outfit_data in outfits.data:
                try:

                    if include_likes and user_id:
                        outfit_data['is_liked'] = len(outfit_data.get("user_outfit_likes", [])) == 1
                    else:
                        outfit_data['is_liked'] = None

                    outfit_obj = DatabaseOutfit(**outfit_data)
                    outfit_objects.append(outfit_obj)
                except Exception as e:
                    logger_service.error(f"Failed to convert outfit {outfit_data.get('id')} to DatabaseOutfit: {str(e)}")
                    continue
            
            # Enrich outfits with their products
            for outfit in outfit_objects:
                outfit.products = await self._get_outfit_products(outfit.id)

            return DatabasePaginatedResponse[DatabaseOutfit](
                data=outfit_objects,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )

        except Exception as e:
            error_msg = f"Failed to retrieve outfits with products: {str(e)}"
            logger_service.error(error_msg)
            return DatabasePaginatedResponse[DatabaseOutfit](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

    async def get_liked_outfits(self, user_id: str, page: int = 1, page_size: int = 10) -> DatabasePaginatedResponse[DatabaseOutfit]:
        """
        Retrieve all outfits that a user has liked with pagination.

        Args:
            user_id: ID of the user whose liked outfits to retrieve
            page: Page number (starting from 1)
            page_size: Number of outfits per page

        Returns:
            DatabasePaginatedResponse containing DatabaseOutfit objects with pagination applied
        """
        try:
            # Calculate offset for pagination
            offset = (page - 1) * page_size

            # Get liked outfits with pagination through junction table
            likes_result = await self.supabase.table("user_outfit_likes").select(
                """
                outfit_id,
                created_at,
                outfits (*)
                """
            ).eq("user_id", user_id).order("created_at", desc=True).range(
                offset, offset + page_size - 1
            ).execute()

            # Get total count for pagination
            count_result = await self.supabase.table("user_outfit_likes").select(
                "outfit_id", count="exact"
            ).eq("user_id", user_id).execute()

            total_count = count_result.count if count_result.count else 0

            # Convert raw outfit data to DatabaseOutfit objects
            outfit_objects = []
            for like_record in likes_result.data:
                if like_record.get("outfits"):
                    try:

                        outfit_data = like_record["outfits"]
                        outfit_obj = DatabaseOutfit(**outfit_data)
                        outfit_obj.is_liked = True # Safe to say outfit is liked..
                        outfit_objects.append(outfit_obj)

                    except Exception as e:
                        logger_service.error(f"Failed to convert liked outfit {outfit_data.get('id')} to DatabaseOutfit: {str(e)}")
                        # Continue processing other outfits instead of failing entirely
                        continue
            
            return DatabasePaginatedResponse[DatabaseOutfit](
                data=outfit_objects,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )
            
        except Exception as e:
            error_msg = f"Failed to retrieve user liked outfits: {str(e)}"
            logger_service.error(error_msg)
            return DatabasePaginatedResponse[DatabaseOutfit](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

    async def get_liked_outfits_with_products(self, user_id: str, page: int = 1, page_size: int = 10) -> DatabasePaginatedResponse[DatabaseOutfit]:
        """
        Retrieve all outfits that a user has liked along with their associated products with pagination.
        
        Args:
            user_id: ID of the user whose liked outfits to retrieve
            page: Page number (starting from 1)
            page_size: Number of outfits per page
            
        Returns:
            DatabasePaginatedResponse containing DatabaseOutfit objects with pagination applied
        """
        try:
            # Get liked outfits
            liked_outfits_result = await self.supabase.table("user_outfit_likes").select(
                """
                outfit_id,
                created_at,
                outfits (*)
                """
            ).eq("user_id", user_id).order("created_at", desc=True).range(
                (page - 1) * page_size, page * page_size - 1
            ).execute()

            # Get total count for pagination
            count_result = await self.supabase.table("user_outfit_likes").select(
                "outfit_id", count="exact"
            ).eq("user_id", user_id).execute()

            total_count = count_result.count if count_result.count else 0

            # Convert raw outfit data to DatabaseOutfit objects
            outfit_objects = []
            for like_record in liked_outfits_result.data:
                if like_record.get("outfits"):
                    try:
                        outfit_data = like_record["outfits"]
                        outfit_obj = DatabaseOutfit(**outfit_data)
                        outfit_obj.is_liked = True # safe to assume it's liked
                        outfit_objects.append(outfit_obj)
                    except Exception as e:
                        logger_service.error(f"Failed to convert liked outfit {outfit_data.get('id')} to DatabaseOutfit: {str(e)}")
                        # Continue processing other outfits instead of failing entirely
                        continue

            # Enrich outfits with their products
            for outfit in outfit_objects:
                outfit.products = await self._get_outfit_products(outfit.id)

            return DatabasePaginatedResponse[DatabaseOutfit](
                data=outfit_objects,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )
        except Exception as e:
            error_msg = f"Failed to retrieve user liked outfits with products: {str(e)}"
            logger_service.error(error_msg)
            return DatabasePaginatedResponse[DatabaseOutfit](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

    async def search_outfits(self, query: str, page: int = 1, page_size: int = 10, threshold: float = 0.5, style: Optional[str] = None) -> DatabasePaginatedResponse[DatabaseOutfit]:
        """
        Search outfits based on semantic similarity to the query using OpenAI embeddings.
        
        This method uses OpenAI embeddings to compute semantic similarity between the search query
        and outfit prompts, providing more intelligent matching than simple text-based searches.
        Results are ranked by similarity score and include associated products.
        
        Args:
            query: Search query string to find semantically similar outfits
            page: Page number for pagination (default is 1)
            page_size: Number of outfits to return per page (default is 10)
            threshold: Minimum similarity score threshold (0.0 to 1.0, default: 0.6)
            style: Filter results by style (optional)
            
        Returns:
            DatabasePaginatedResponse containing DatabaseOutfit objects with pagination applied
            
        Raises:
            ValueError: If query is empty or too short
        """
        try:
            # Validate and normalize query parameter
            if not query or len(query.strip()) < 2:
                logger_service.warning("Search query must be at least 2 characters long")
                raise ValueError("Search query must be at least 2 characters long")
            
            # Normalize the search query
            normalized_query = self._normalize_search_query(query)
            
            logger_service.info(f"Searching outfits with semantic similarity for query: '{normalized_query}' (original: '{query}'), page: {page}, page_size: {page_size}, threshold: {threshold}, style: {style}")
            
            # Step 1: Get all outfits with user_prompt, applying style filter if provided
            outfit_query = self.supabase.table("outfits").select("*")
            if style:
                style_values = [s.strip().lower() for s in style.split(',') if s.strip()]
                if len(style_values) == 1:
                    # Single value - use simple ilike for case-insensitive matching
                    outfit_query = outfit_query.ilike("style", f"%{style_values[0]}%")
                elif len(style_values) > 1:
                    # Multiple values - use OR logic
                    style_conditions = ",".join([f'style.ilike.%{style_val}%' for style_val in style_values])
                    outfit_query = outfit_query.or_(style_conditions)
            
            all_outfits_result = await outfit_query.execute()

            if not all_outfits_result.data:
                logger_service.info("No outfits found for search comparison")
                return DatabasePaginatedResponse[DatabaseOutfit](
                    data=[],
                    total_count=0,
                    page=page,
                    page_size=page_size,
                    success=True
                )
            
            # Step 2: Get embedding for normalized search query
            logger_service.debug(f"Generating embedding for normalized query: '{normalized_query}'") 
            query_embedding = self._get_text_embedding(normalized_query)
            
            # Step 3: Filter outfits with user_prompt and get their embeddings
            outfits_with_prompts = []
            outfit_texts = []

            for outfit_data in all_outfits_result.data:
                user_prompt = outfit_data.get("user_prompt", "")
                if user_prompt and user_prompt.strip():
                    outfits_with_prompts.append(outfit_data)
                    outfit_texts.append(user_prompt)
            
            if not outfit_texts:
                logger_service.info("No outfits with user prompts found for semantic search")
                return DatabasePaginatedResponse[DatabaseOutfit](
                    data=[],
                    total_count=0,
                    page=page,
                    page_size=page_size,
                    success=True
                )
            
            # Get batch embeddings for efficiency
            outfit_embeddings = self._get_batch_text_embeddings(outfit_texts)
            
            # Step 4: Calculate similarities and filter by threshold
            matching_outfits = []
            
            for i, (outfit_data, embedding) in enumerate(zip(outfits_with_prompts, outfit_embeddings)):
                similarity_score = self._cosine_similarity(query_embedding, embedding)

                if similarity_score >= threshold:
                    try:
                        outfit_obj = DatabaseOutfit(**outfit_data)
                        # Store similarity score as a custom attribute
                        outfit_obj.__dict__['similarity_score'] = similarity_score
                        matching_outfits.append((similarity_score, outfit_obj))
                    except Exception as e:
                        logger_service.error(f"Failed to convert outfit {outfit_data.get('id')} to DatabaseOutfit: {str(e)}")
                        continue
            
            # Step 5: Sort by similarity score (highest first)
            matching_outfits.sort(key=lambda x: x[0], reverse=True)
            
            # Step 6: Apply pagination to the sorted results
            total_count = len(matching_outfits)
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_outfits = [outfit for _, outfit in matching_outfits[start_index:end_index]]
            
            # Step 7: Enrich with products
            for outfit in paginated_outfits:
                outfit.products = await self._get_outfit_products(outfit.id)
            
            success_msg = f"Found {total_count} outfits matching query '{query}' with similarity >= {threshold}"
            logger_service.success(success_msg)

            return DatabasePaginatedResponse[DatabaseOutfit](
                data=paginated_outfits,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )

        except ValueError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            error_msg = f"Failed to search outfits: {str(e)}"
            logger_service.error(error_msg)
            return DatabasePaginatedResponse[DatabaseOutfit](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

    async def insert_outfit_with_products(self, outfit: DatabaseOutfit, products: List[DatabaseProduct]) -> Dict[str, Any]:
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
                logger_service.info(f"Inserting {len(products)} products for outfit: {outfit.name or 'Unknown'}")
                
                for product in products:
                    try:
                        # Convert Pydantic model to dict for Supabase
                        product_data = product.model_dump(exclude_unset=True)
                        
                        # Use upsert to handle existing products gracefully
                        result = await self.supabase.table("products").upsert(
                            product_data, 
                            on_conflict="id"
                        ).execute()
                        
                        if result.data:
                            inserted_products.append(product.id)
                            logger_service.success(f"Product {product.id} inserted/updated successfully")
                        
                    except Exception as e:
                        logger_service.error(f"Failed to insert product {product.id}: {str(e)}")
                        # Continue with other products even if one fails
                        continue

            # Step 2: Insert the outfit
            logger_service.info(f"Inserting outfit: {outfit.name or 'Unknown'}")
            outfit_data = outfit.model_dump(exclude_unset=True)

            outfit_result = await self.supabase.table("outfits").insert(outfit_data).execute()

            if not outfit_result.data:
                raise Exception("Failed to insert outfit")
                
            outfit_id = outfit_result.data[0]["id"]
            logger_service.success(f"Outfit {outfit_id} inserted successfully")

            # Step 3: Create relationships in product_outfit_junction
            if inserted_products:
                logger_service.info(f"Creating product-outfit relationships for outfit {outfit_id}")
                
                junction_data = [
                    {
                        "outfit_id": outfit_id,
                        "product_id": product_id,
                        "created_at": datetime.utcnow().isoformat()
                    }
                    for product_id in inserted_products
                ]

                junction_result = await self.supabase.table("product_outfit_junction").insert(
                    junction_data
                ).execute()
                
                if junction_result.data:
                    logger_service.success(f"Successfully created relationships for outfit {outfit_id}")

            return {
                "success": True,
                "outfit_id": outfit_id,
                "inserted_products": inserted_products,
                "message": f"Successfully created outfit with {len(inserted_products)} products"
            }

        except Exception as e:
            error_msg = f"Failed to insert outfit with products: {str(e)}"
            logger_service.error(error_msg)
            return {
                "success": False,
                "outfit_id": None,
                "inserted_products": [],
                "message": error_msg
            }

    async def like_outfit(self, user_id: str, outfit_id: int) -> DatabaseLikeResponse:
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
            dislike_result = await self.supabase.table("user_outfit_dislikes").delete().eq(
                "user_id", user_id
            ).eq("outfit_id", outfit_id).execute()
            
            if dislike_result.data:
                logger_service.info(f"Removed existing dislike for user {user_id}, outfit {outfit_id}")
            
            # Step 2: Add to likes table (upsert to handle duplicates)
            like_data = {
                "user_id": user_id,
                "outfit_id": outfit_id,
                "created_at": datetime.utcnow().isoformat()
            }

            like_result = await self.supabase.table("user_outfit_likes").upsert(
                like_data,
                on_conflict="user_id,outfit_id"
            ).execute()
            
            if like_result.data:
                return DatabaseLikeResponse(
                    success=True,
                    message=f"Successfully liked outfit {outfit_id}",
                    is_liked=True
                )
            else:
                raise Exception("Failed to insert like record")

        except Exception as e:
            error_msg = f"Failed to like outfit {outfit_id} for user {user_id}: {str(e)}"
            logger_service.error(error_msg)
            return DatabaseLikeResponse(
                success=False,
                message=error_msg,
                is_liked=False
            )

    async def dislike_outfit(self, user_id: str, outfit_id: int) -> DatabaseLikeResponse:
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
            like_result = await self.supabase.table("user_outfit_likes").delete().eq(
                "user_id", user_id
            ).eq("outfit_id", outfit_id).execute()
            
            if like_result.data:
                logger_service.info(f"Removed existing like for user {user_id}, outfit {outfit_id}")
            
            # Step 2: Add to dislikes table (upsert to handle duplicates)
            dislike_data = {
                "user_id": user_id,
                "outfit_id": outfit_id,
                "created_at": datetime.utcnow().isoformat()
            }
            dislike_result = await self.supabase.table("user_outfit_dislikes").upsert(
                dislike_data,
                on_conflict="user_id,outfit_id"
            ).execute()
            
            if dislike_result.data:
                return DatabaseLikeResponse(
                    success=True,
                    message=f"Successfully unliked outfit {outfit_id}",
                    is_liked=False
                )
            else:
                raise Exception("Failed to insert dislike record")
        except Exception as e:
            error_msg = f"Failed to unlike outfit {outfit_id} for user {user_id}: {str(e)}"
            logger_service.error(error_msg)
            return DatabaseLikeResponse(
                success=False,
                message=error_msg,
                is_liked=False
            )

    async def find_similar_outfits(
        self, 
        outfit_id: int, 
        limit: int = 10,
        threshold: float = 0.7
    ) -> DatabaseSimilarityResponse[DatabaseOutfit]:
        """
        Find outfits similar to the given outfit based on semantic similarity of user prompts.
        
        This method uses OpenAI embeddings to compute semantic similarity between outfit prompts,
        providing more intelligent matching than simple text-based searches.
        
        Args:
            outfit_id: ID of the target outfit to find similar outfits for
            limit: Maximum number of similar outfits to return (default: 10)
            threshold: Minimum similarity score threshold (0.0 to 1.0, default: 0.7)
            
        Returns:
            DatabaseSimilarityResponse containing:
                - success: Boolean indicating operation success
                - message: Success or error message
                - data: List of similar DatabaseOutfit objects
                - target: The target DatabaseOutfit object
                
        Raises:
            Exception: If target outfit not found or similarity computation fails
        """
        try:
            logger_service.info(f"Finding similar outfits for outfit {outfit_id} with threshold {threshold}")
            
            # Step 1: Get the target outfit
            target_outfit = await self.get_outfit(outfit_id)

            if not target_outfit:
                error_msg = f"Target outfit {outfit_id} not found"
                logger_service.error(error_msg)
                return DatabaseSimilarityResponse[DatabaseOutfit](
                    success=False,
                    message=error_msg,
                    data=[],
                    target=None
                )

            # Step 2: Get all other outfits (excluding the target)
            all_outfits_result = await self.supabase.table("outfits").select(
                "id, name, description, image_url, user_prompt, style, points"
            ).neq("id", outfit_id).execute()
            
            if not all_outfits_result.data:
                logger_service.info("No other outfits found for comparison")
                return DatabaseSimilarityResponse[DatabaseOutfit](
                    success=True,
                    message="No other outfits available for comparison",
                    data=[],
                    target=target_outfit
                )
            
            # Step 3: Get embedding for target outfit's user_prompt
            target_text = target_outfit.user_prompt or ""
            if not target_text.strip():
                logger_service.warning(f"Target outfit {outfit_id} has no user_prompt for similarity comparison")
                return DatabaseSimilarityResponse[DatabaseOutfit](
                    success=False,
                    message="Target outfit has no user prompt for similarity comparison",
                    data=[],
                    target=target_outfit
                )
            
            target_embedding = self._get_text_embedding(target_text)
            
            # Step 4: Get embeddings for all other outfits' user_prompts
            other_outfits = []
            other_texts = []
            
            for outfit_data in all_outfits_result.data:
                user_prompt = outfit_data.get("user_prompt", "")
                if user_prompt and user_prompt.strip():
                    other_outfits.append(outfit_data)
                    other_texts.append(user_prompt)
            
            if not other_texts:
                logger_service.info("No other outfits with user prompts found for comparison")
                return DatabaseSimilarityResponse[DatabaseOutfit](
                    success=True,
                    message="No other outfits with user prompts available for comparison",
                    data=[],
                    target=target_outfit
                )
            
            # Get batch embeddings for efficiency
            other_embeddings = self._get_batch_text_embeddings(other_texts)
            
            # Step 5: Calculate similarities and filter by threshold
            similar_outfits = []
            
            for i, (outfit_data, embedding) in enumerate(zip(other_outfits, other_embeddings)):
                similarity_score = self._cosine_similarity(target_embedding, embedding)
                
                if similarity_score >= threshold:
                    # Convert to DatabaseOutfit object and add similarity score
                    try:
                        outfit_obj = DatabaseOutfit(**outfit_data)
                        # Store similarity score as a custom attribute (not part of the model)
                        outfit_obj.__dict__['similarity_score'] = similarity_score
                        similar_outfits.append((similarity_score, outfit_obj))
                    except Exception as e:
                        logger_service.error(f"Failed to convert outfit {outfit_data.get('id')} to DatabaseOutfit: {str(e)}")
                        continue
            
            # Step 6: Sort by similarity score (highest first) and limit results
            similar_outfits.sort(key=lambda x: x[0], reverse=True)
            limited_outfits = [outfit for _, outfit in similar_outfits[:limit]]
            
            # Step 7: Enrich with products if needed
            for outfit in limited_outfits:
                outfit.products = await self._get_outfit_products(outfit.id)
            
            success_msg = f"Found {len(limited_outfits)} similar outfits for outfit {outfit_id}"
            logger_service.success(success_msg)
            
            return DatabaseSimilarityResponse[DatabaseOutfit](
                success=True,
                message=success_msg,
                data=limited_outfits,
                target=target_outfit
            )
            
        except Exception as e:
            error_msg = f"Failed to find similar outfits for outfit {outfit_id}: {str(e)}"
            logger_service.error(error_msg)
            return DatabaseSimilarityResponse[DatabaseOutfit](
                success=False,
                message=error_msg,
                data=[],
                target=None
            )

# === PRODUCTS CRUD OPERATIONS ===
    async def get_product(self, product_id: str) -> Optional[DatabaseProduct]:
        """
        Retrieve a single product by its ID.

        Args:
            product_id: ID of the product to retrieve

        Returns:
            DatabaseProduct object if found, None otherwise
        """
        try:
            result = await self.supabase.table("products").select("*").eq("id", product_id).execute()
            if result.data:
                return DatabaseProduct(**result.data[0])
            return None
        except Exception as e:
            logger_service.error(f"Failed to retrieve product {product_id}: {str(e)}")
            return None

    async def get_products(self, page: int = 1, page_size: int = 10, user_id: str = None, include_likes: bool = True, brand: Optional[str] = None, type: Optional[str] = None) -> DatabasePaginatedResponse[DatabaseProduct]:
        """
        Retrieve a paginated list of products with optional filtering.

        Args:
            page: Page number (starting from 1)
            page_size: Number of products per page
            user_id: User ID for including like information
            include_likes: Whether to include user likes in the response
            brand: Optional filter by brand name (case-insensitive)
            type: Optional filter by product type (case-insensitive)

        Returns:
            DatabasePaginatedResponse containing:
                - data: List of DatabaseProduct objects
                - total_count: Total number of products
                - page: Current page number
                - page_size: Number of items per page
                - success: Boolean indicating operation success
        """
        try:
            # Calculate offset for pagination
            offset = (page - 1) * page_size

            # Build the base query
            if include_likes and user_id:
                query = self.supabase.table("products").select("*, user_product_likes!left(product_id)").eq("user_product_likes.user_id", user_id)
                count_query = self.supabase.table("products").select("id", count="exact")
            else:
                query = self.supabase.table("products").select("*")
                count_query = self.supabase.table("products").select("id", count="exact")

            # Apply brand filter if provided (supports comma-separated values with OR logic)
            if brand:
                brand_values = [b.strip().lower() for b in brand.split(',') if b.strip()]
                if len(brand_values) == 1:
                    # Single value - use simple ilike
                    query = query.ilike("brand", f"%{brand_values[0]}%")
                    count_query = count_query.ilike("brand", f"%{brand_values[0]}%")
                elif len(brand_values) > 1:
                    # Multiple values - use OR logic
                    brand_conditions = ",".join([f'brand.ilike.%{brand_val}%' for brand_val in brand_values])
                    query = query.or_(brand_conditions)
                    count_query = count_query.or_(brand_conditions)

            # Apply type filter if provided (supports comma-separated values with OR logic)
            if type:
                type_values = [t.strip().lower() for t in type.split(',') if t.strip()]
                if len(type_values) == 1:
                    # Single value - use simple ilike
                    query = query.ilike("type", f"%{type_values[0]}%")
                    count_query = count_query.ilike("type", f"%{type_values[0]}%")
                elif len(type_values) > 1:
                    # Multiple values - use OR logic
                    type_conditions = ",".join([f'type.ilike.%{type_val}%' for type_val in type_values])
                    query = query.or_(type_conditions)
                    count_query = count_query.or_(type_conditions)

            # Execute the main query with pagination
            result = await query.range(offset, offset + page_size - 1).execute()

            # Get total count with the same filters
            count_result = await count_query.execute()
            total_count = count_result.count if count_result.count else 0

            # Convert raw product data to DatabaseProduct objects
            product_objects: List[DatabaseProduct] = []
            for product_data in result.data:
                try:
                    if include_likes and user_id:
                        product_data['is_liked'] = len(product_data.get("user_product_likes", [])) == 1
                    else:
                        product_data['is_liked'] = None

                    product_obj = DatabaseProduct(**product_data)
                    product_objects.append(product_obj)
                except Exception as e:
                    logger_service.error(f"Failed to convert product {product_data.get('id')} to DatabaseProduct: {str(e)}")
                    # Continue processing other products instead of failing entirely
                    continue

            return DatabasePaginatedResponse[DatabaseProduct](
                data=product_objects,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )

        except Exception as e:
            error_msg = f"Failed to retrieve products: {str(e)}"
            logger_service.error(error_msg)
            return DatabasePaginatedResponse[DatabaseProduct](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

    async def get_liked_products(self, user_id: str, page: int = 1, page_size: int = 10) -> DatabasePaginatedResponse[DatabaseProduct]:
        """
        Retrieve all products that a user has liked with pagination.

        Args:
            user_id: ID of the user whose liked products to retrieve
            page: Page number (starting from 1)
            page_size: Number of products per page

        Returns:
            DatabasePaginatedResponse containing:
                - data: List of DatabaseProduct objects
                - total_count: Total number of liked products
                - page: Current page number
                - page_size: Number of items per page
                - success: Boolean indicating operation success
        """
        try:
            # Calculate offset for pagination
            offset = (page - 1) * page_size

            # Get liked products with pagination through junction table
            likes_result = await self.supabase.table("user_product_likes").select(
                """
                product_id,
                created_at,
                products (*)
                """
            ).eq("user_id", user_id).order("created_at", desc=True).range(
                offset, offset + page_size - 1
            ).execute()

            # Get total count for pagination
            count_result = await self.supabase.table("user_product_likes").select(
                "product_id", count="exact"
            ).eq("user_id", user_id).execute()

            total_count = count_result.count if count_result.count else 0

            # Convert raw product data to DatabaseProduct objects
            product_objects: List[DatabaseProduct] = []
            for like_record in likes_result.data:
                if like_record.get("products"):
                    try:
                        product_data = like_record["products"]
                        # Set is_liked to True since these are liked products
                        product_data['is_liked'] = True
                        product_obj = DatabaseProduct(**product_data)
                        product_objects.append(product_obj)
                    except Exception as e:
                        logger_service.error(f"Failed to convert liked product {product_data.get('id')} to DatabaseProduct: {str(e)}")
                        # Continue processing other products instead of failing entirely
                        continue

            return DatabasePaginatedResponse[DatabaseProduct](
                data=product_objects,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )

        except Exception as e:
            error_msg = f"Failed to retrieve user liked products: {str(e)}"
            logger_service.error(error_msg)
            return DatabasePaginatedResponse[DatabaseProduct](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

    async def like_product(self, user_id: str, product_id: str) -> DatabaseLikeResponse:
        """
        Like a product for a user by managing both likes and dislikes tables.
        
        This method performs the following operations:
        1. Remove any existing dislike for this user/product combination
        2. Add a like entry (using upsert to handle duplicate likes gracefully)
        
        Args:
            user_id: ID of the user liking the product
            product_id: ID of the product being liked
            
        Returns:
            Dict containing:
                - success: Boolean indicating operation success
                - message: Success or error message
                
        Raises:
            Exception: If database operations fail
        """
        try:
            # Step 1: Remove from dislikes table if exists
            dislike_result = await self.supabase.table("user_product_dislikes").delete().eq(
                "user_id", user_id
            ).eq("product_id", product_id).execute()
            
            if dislike_result.data:
                logger_service.info(f"Removed existing dislike for user {user_id}, product {product_id}")
            
            # Step 2: Add to likes table (upsert to handle duplicates)
            like_data = {
                "user_id": user_id,
                "product_id": product_id,
                "created_at": datetime.utcnow().isoformat()
            }

            like_result = await self.supabase.table("user_product_likes").upsert(
                like_data,
                on_conflict="user_id,product_id"
            ).execute()
            
            if like_result.data:
                return DatabaseLikeResponse(
                    success=True,
                    message=f"Successfully liked product {product_id}",
                    is_liked=True
                )
            else:
                raise Exception("Failed to insert like record")
                
        except Exception as e:
            error_msg = f"Failed to like product {product_id} for user {user_id}: {str(e)}"
            logger_service.error(error_msg)
            return DatabaseLikeResponse(
                success=False,
                message=error_msg,
                is_liked=False
            )

    async def dislike_product(self, user_id: str, product_id: str) -> DatabaseLikeResponse:
        """
        Dislike a product for a user by managing both likes and dislikes tables.
        
        This method performs the following operations:
        1. Remove any existing like for this user/product combination
        2. Add a dislike entry (using upsert to handle duplicate dislikes gracefully)
        
        Args:
            user_id: ID of the user disliking the product
            product_id: ID of the product being disliked
            
        Returns:
            Dict containing:
                - success: Boolean indicating operation success
                - message: Success or error message
                
        Raises:
            Exception: If database operations fail
        """
        try:
            # Step 1: Remove from likes table if exists
            like_result = await self.supabase.table("user_product_likes").delete().eq(
                "user_id", user_id
            ).eq("product_id", product_id).execute()
            
            if like_result.data:
                logger_service.info(f"Removed existing like for user {user_id}, product {product_id}")
            
            # Step 2: Add to dislikes table (upsert to handle duplicates)
            dislike_data = {
                "user_id": user_id,
                "product_id": product_id,
                "created_at": datetime.utcnow().isoformat()
            }

            dislike_result = await self.supabase.table("user_product_dislikes").upsert(
                dislike_data,
                on_conflict="user_id,product_id"
            ).execute()
            
            if dislike_result.data:
                return DatabaseLikeResponse(
                    success=True,
                    message=f"Successfully disliked product {product_id}",
                    is_liked=False
                )
            else:
                raise Exception("Failed to insert dislike record")
                
        except Exception as e:
            error_msg = f"Failed to dislike product {product_id} for user {user_id}: {str(e)}"
            logger_service.error(error_msg)
            return DatabaseLikeResponse(
                success=False,
                message=error_msg,
                is_liked=False
            )

    async def insert_product(self, product: DatabaseProduct) -> Dict[str, Any]:
        """
        Insert a new product into the database.
        
        Args:
            product: DatabaseProduct model containing product information
            
        Returns:
            Dict containing:
                - success: Boolean indicating operation success
                - product_id: ID of the created product
                - message: Success or error message
                
        Raises:
            Exception: If database operation fails
        """
        try:
            # Convert Pydantic model to dict for Supabase
            product_data = product.model_dump(exclude_unset=True)
            
            # Insert the product into the products table
            result = await self.supabase.table("products").upsert(product_data, on_conflict="id").execute()

            if not result.data:
                raise Exception("Failed to insert product")
                
            product_id = result.data[0]["id"]
            logger_service.success(f"Product {product_id} inserted successfully")
            
            return {
                "success": True,
                "product_id": product_id,
                "message": f"Successfully created product {product.title or 'Unknown'}"
            }
            
        except Exception as e:
            error_msg = f"Failed to insert product: {str(e)}\nProduct data: {product.model_dump()}"
            logger_service.error(error_msg)
            return {
                "success": False,
                "product_id": None,
                "message": error_msg
            }
        

# === SEMANTIC EMBEDDING METHODS ===
    def _get_text_embedding(self, text: str) -> List[float]:
        """
        Get OpenAI embedding for a single text string.
        
        Args:
            text: Text to generate embedding for
            
        Returns:
            List of floats representing the text embedding
        """
        try:
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",  # Cost-effective model
                input=text.strip()
            )
            return response.data[0].embedding
        except Exception as e:
            logger_service.error(f"Failed to get embedding for text: {str(e)}")
            raise
    
    def _get_batch_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get OpenAI embeddings for a batch of text strings.
        
        Args:
            texts: List of texts to generate embeddings for
            
        Returns:
            List of embeddings (each embedding is a list of floats)
        """
        try:
            # Clean and prepare texts
            cleaned_texts = [text.strip() for text in texts if text and text.strip()]
            
            if not cleaned_texts:
                return []
            
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=cleaned_texts
            )
            
            return [item.embedding for item in response.data]
        except Exception as e:
            logger_service.error(f"Failed to get batch embeddings: {str(e)}")
            raise
    
    def _cosine_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """
        Calculate cosine similarity between two embeddings.
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Cosine similarity score between 0 and 1
        """
        try:
            # Convert to numpy arrays for efficient computation
            a = np.array(embedding1)
            b = np.array(embedding2)
            
            # Calculate cosine similarity
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            
            similarity = dot_product / (norm_a * norm_b)
            
            # Ensure result is between 0 and 1
            return max(0.0, min(1.0, similarity))
            
        except Exception as e:
            logger_service.error(f"Failed to calculate cosine similarity: {str(e)}")
            return 0.0

    def _normalize_search_query(self, query: str) -> str:
        """
        Normalize a search query for better matching consistency.
        
        This method performs the following normalizations:
        - Convert to lowercase
        - Strip leading/trailing whitespace
        - Replace multiple consecutive spaces with single spaces
        - Remove special characters that don't add semantic value
        
        Args:
            query: Raw search query string
            
        Returns:
            Normalized query string
        """
        try:
            import re
            
            if not query:
                return ""
            
            # Convert to lowercase and strip whitespace
            normalized = query.lower().strip()
            
            # Replace multiple consecutive whitespace with single spaces
            normalized = re.sub(r'\s+', ' ', normalized)
            
            # Remove extra punctuation that doesn't add semantic value
            # Keep basic punctuation like apostrophes, hyphens, and periods
            normalized = re.sub(r'[^\w\s\'-.]', ' ', normalized)
            
            # Clean up any double spaces created by punctuation removal
            normalized = re.sub(r'\s+', ' ', normalized)
            
            # Final strip
            normalized = normalized.strip()
            
            logger_service.debug(f"Normalized query '{query}' to '{normalized}'")
            return normalized
        except Exception as e:
            logger_service.error(f"Failed to calculate cosine similarity: {str(e)}")
            return 0.0

# === STORAGE METHODS ===
    async def upload_image(self, bucket: str, file_name: str, data: bytes) -> str:
        """
        Uploads a binary file to a Supabase storage bucket and returns the public URL.
        If a file with the same name already exists, returns the existing file's public URL.

        :param bucket: The name of the storage bucket.
        :param file_name: The name of the file to save in the bucket.
        :param data: The binary data of the file.
        :return: The public URL of the uploaded (or existing) file.
        """
        try:
            # Attempt to upload the file to the specified bucket
            response = await self.supabase.storage.from_(bucket).upload(file_name, data, file_options={"contentType": "image/png"})
            logger_service.info(f"Uploaded file {file_name} to Supabase storage with response: {response}")

        except Exception as upload_error:
            # Check if the error is due to file already existing
            error_message = str(upload_error).lower()
            if any(keyword in error_message for keyword in ['already exists', 'duplicate', 'conflict', 'exists']):
                logger_service.info(f"File {file_name} already exists in bucket {bucket}, returning existing public URL")
            else:
                # Re-raise if it's a different error
                logger_service.error(f"Failed to upload file {file_name} to bucket {bucket}: {str(upload_error)}")
                raise

        # Generate the public URL for the uploaded (or existing) file
        public_url = await self.supabase.storage.from_(bucket).get_public_url(file_name)
        return public_url

# === HELPER METHODS ===
    async def _get_outfit_products(self, outfit_id: int) -> Optional[List[DatabaseProduct]]:
        """
        Retrieve all products associated with a specific outfit.
        
        Args:
            outfit_id: ID of the outfit to retrieve products for
            
        Returns:
            List of DatabaseProduct objects if found, or None if not found
        """
        try:
            # Get products through junction table
            products_result = await self.supabase.table("product_outfit_junction").select(
                "products (*)"
            ).eq("outfit_id", outfit_id).execute()
            
            if not products_result.data:
                return None
            
            # Extract product data and convert to DatabaseProduct objects
            products: List[DatabaseProduct] = []
            for item in products_result.data:
                if item.get("products"):
                    try:
                        product_data = item["products"]
                        product_obj = DatabaseProduct(**product_data)
                        products.append(product_obj)
                    except Exception as e:
                        logger_service.error(f"Failed to convert product to DatabaseProduct: {str(e)}")
                        # Continue processing other products instead of failing entirely
                        continue
            
            return products

        except Exception as e:
            logger_service.error(f"Failed to retrieve products for outfit {outfit_id}: {str(e)}")
            return None

    async def search_products(self, query: str, page: int = 1, page_size: int = 10, brand: Optional[str] = None, type: Optional[str] = None) -> DatabasePaginatedResponse[DatabaseProduct]:
        """
        Search products using PostgreSQL ilike operator on the search_query column with optional filtering.
        
        This method performs a case-insensitive text search using PostgreSQL's ilike operator
        on the search_query column, allowing for pattern matching and partial text searches.
        Can be combined with brand and type filters for more refined results.
        
        Args:
            query: Search query string to match against product search_query column
            page: Page number for pagination (default is 1)
            page_size: Number of products to return per page (default is 10)
            brand: Optional filter by brand name (case-insensitive)
            type: Optional filter by product type (case-insensitive)
            
        Returns:
            DatabasePaginatedResponse containing DatabaseProduct objects with pagination applied
            
        Raises:
            ValueError: If query is empty or too short
        """
        try:
            # Validate query parameter
            if not query or len(query.strip()) < 2:
                logger_service.warning("Search query must be at least 2 characters long")
                raise ValueError("Search query must be at least 2 characters long")

            # Prepare the search pattern for ilike (case-insensitive like)
            search_pattern = f"%{query.strip()}%"
            
            logger_service.info(f"Searching products using ilike for pattern: '{search_pattern}', page: {page}, page_size: {page_size}, brand: {brand}, type: {type}")

            # Calculate offset for pagination
            offset = (page - 1) * page_size

            # Build the base query for products search
            products_query = self.supabase.table("products").select("*").ilike("search_query", search_pattern)
            count_query = self.supabase.table("products").select("id", count="exact").ilike("search_query", search_pattern)

            # Apply brand filter if provided (supports comma-separated values with OR logic)
            if brand:
                brand_values = [b.strip().lower() for b in brand.split(',') if b.strip()]
                if len(brand_values) == 1:
                    # Single value - use simple ilike
                    products_query = products_query.ilike("brand", f"%{brand_values[0]}%")
                    count_query = count_query.ilike("brand", f"%{brand_values[0]}%")
                elif len(brand_values) > 1:
                    # Multiple values - use OR logic
                    brand_conditions = ",".join([f'brand.ilike.%{brand_val}%' for brand_val in brand_values])
                    products_query = products_query.or_(brand_conditions)
                    count_query = count_query.or_(brand_conditions)

            # Apply type filter if provided (supports comma-separated values with OR logic)
            if type:
                type_values = [t.strip().lower() for t in type.split(',') if t.strip()]
                if len(type_values) == 1:
                    # Single value - use simple ilike
                    products_query = products_query.ilike("type", f"%{type_values[0]}%")
                    count_query = count_query.ilike("type", f"%{type_values[0]}%")
                elif len(type_values) > 1:
                    # Multiple values - use OR logic
                    type_conditions = ",".join([f'type.ilike.%{type_val}%' for type_val in type_values])
                    products_query = products_query.or_(type_conditions)
                    count_query = count_query.or_(type_conditions)

            # Execute the search query with pagination
            products_result = await products_query.range(offset, offset + page_size - 1).execute()

            # Get total count with the same filters
            count_result = await count_query.execute()
            
            total_count = count_result.count if count_result.count else 0

            # Step 3: Convert raw product data to DatabaseProduct objects
            product_objects = []
            for product_data in products_result.data:
                try:
                    # Handle potential missing fields with default values
                    product_obj = DatabaseProduct(
                        id=product_data["id"],
                        type=product_data.get("type", ""),
                        search_query=product_data.get("search_query", ""),
                        link=product_data.get("link", ""),
                        title=product_data.get("title", ""),
                        price=float(product_data.get("price", 0)) if product_data.get("price") else 0.0,
                        images=product_data.get("images", []),
                        brand=product_data.get("brand", ""),
                        description=product_data.get("description", ""),
                        color=product_data.get("color", ""),
                        points=int(product_data.get("points", 0)) if product_data.get("points") else 0,
                        style=product_data.get("style", "")
                    )
                    product_objects.append(product_obj)
                except Exception as e:
                    logger_service.error(f"Failed to convert product {product_data.get('id')} to DatabaseProduct: {str(e)}")
                    # Continue processing other products instead of failing entirely
                    continue

            success_msg = f"Found {total_count} products matching query '{query}'"
            logger_service.success(success_msg)

            return DatabasePaginatedResponse[DatabaseProduct](
                data=product_objects,
                total_count=total_count,
                page=page,
                page_size=page_size,
                success=True
            )

        except ValueError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            error_msg = f"Failed to search products: {str(e)}"
            logger_service.error(error_msg)
            return DatabasePaginatedResponse[DatabaseProduct](
                data=[],
                total_count=0,
                page=page,
                page_size=page_size,
                success=False
            )

# Create a singleton instance for use across the application
db_service = DatabaseService()

async def get_database_service() -> DatabaseService:
    """
    Dependency function to get the database service instance.
    Use this in FastAPI route dependencies.
    
    Returns:
        DatabaseService: Singleton database service instance
    """

    await db_service.initialize_client()
    return db_service