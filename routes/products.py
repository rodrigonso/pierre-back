from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import datetime
import uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from utils.models import User
from utils.auth import get_current_user
from services.db import get_database_service, DatabaseService
from services.logger import get_logger_service

# Create router for product endpoints
router = APIRouter()
logger_service = get_logger_service()
database_service = get_database_service()

# ============================================================================
# PYDANTIC MODELS FOR REQUEST/RESPONSE
# ============================================================================

class ProductData(BaseModel):
    """Model for individual product data"""
    id: str
    title: str
    brand: str
    type: str
    price: float
    description: str
    images: List[str] = []
    link: str
    search_query: str
    color: str
    style: str
    created_at: datetime
    points: int

class ProductsResponse(BaseModel):
    """Response model for products listing"""
    products: List[ProductData]
    total_count: int
    page: int
    page_size: int
    success: bool = True

class SearchProductsResponse(BaseModel):
    """Response model for product search"""
    query: str
    products: List[ProductData]
    total_count: int
    page: int
    page_size: int
    success: bool = True

class LikeProductResponse(BaseModel):
    """Response model for product like/unlike operations"""
    success: bool
    message: str
    product_id: str
    is_liked: bool

class LikedProductResponse(ProductData):
    """Response model for liked products"""
    is_liked: bool = True  # Indicates if the product is liked by the user

# ============================================================================
# PRODUCT ENDPOINTS
# ============================================================================

@router.get("/products/", response_model=ProductsResponse)
async def get_products(
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of products per page"),
    include_likes: bool = Query(False, description="Include user likes in response"),
    current_user: User = Depends(get_current_user) # just to ensure user is authenticated, not used in this endpoint
):
    """
    Get all products with pagination and optional filtering.
    
    Returns a paginated list of all products in the database.
    Supports filtering by product type and brand.
    """
    try:
        logger_service.info(f"Fetching products - Page: {page}, Size: {page_size}")
        
        result = database_service.get_products(
            page=page,
            page_size=page_size,
        )
        
        # Convert results to ProductData models
        products = []
        for product in result["products"]:
            # Parse created_at if it exists
            created_at = None
            if product.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(product["created_at"].replace('Z', '+00:00'))
                except:
                    created_at = None

            product = ProductData(
                id=product["id"],
                title=product["title"],
                brand=product["brand"],
                type=product["type"],
                price=product["price"],
                description=product["description"],
                images=product["images"],
                link=product["link"],
                search_query=product["search_query"],
                style=product["style"],
                color=product["color"],
                points=product["points"],
                created_at=created_at
            )
            products.append(product)
        
        logger_service.success(f"Successfully retrieved {len(products)} products")
        
        return ProductsResponse(
            products=products,
            total_count=result["total_count"],
            page=result["page"],
            page_size=result["page_size"],
            success=True
        )
        
    except Exception as e:
        logger_service.error(f"Failed to retrieve products: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve products: {str(e)}")

@router.get("/products/search/", response_model=SearchProductsResponse)
async def search_products(
    query: str = Query(..., description="Search query for products"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, description="Number of items per page"),
    current_user: User = Depends(get_current_user), # just to ensure user is authenticated
):
    """
    Search products by query string with pagination
    
    Searches across product titles, descriptions, brands, and search queries.
    Returns matching products ordered by relevance and creation date.
    """
    try:
        logger_service.info(f"Searching products for query: '{query}' - Page: {page}, Size: {page_size}")
        
        # Calculate offset for pagination
        offset = (page - 1) * page_size
        
        # Build search query using PostgreSQL text search
        # Search across title, description, brand, and search_query fields
        search_query = database_service.supabase.table("products").select("*")
        
        # Use OR conditions to search multiple fields with ILIKE for case-insensitive partial matching
        search_conditions = f"title.ilike.%{query}%,type.ilike.%{query}%,color.ilike.%{query}%,style.ilike.%{query}%,description.ilike.%{query}%,brand.ilike.%{query}%,search_query.ilike.%{query}%"
        search_query = search_query.or_(search_conditions)
                
        # Execute search with pagination and ordering
        result = search_query.order("created_at", desc=True).range(
            offset, offset + page_size - 1
        ).execute()
        
        # Get total count for pagination (with same search conditions)
        count_query = database_service.supabase.table("products").select("id", count="exact")
        count_query = count_query.or_(search_conditions)
        
        count_result = count_query.execute()
        total_count = count_result.count if count_result.count else 0
        
        # Convert results to ProductData models
        products = []
        for product_data in result.data:
            # Parse created_at if it exists
            created_at = None
            if product_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(product_data["created_at"].replace('Z', '+00:00'))
                except:
                    created_at = None
            
            product = ProductData(
                id=product_data["id"],
                title=product_data.get("title"),
                brand=product_data.get("brand"),
                points=product_data.get("points"),
                style=product_data.get("style"),
                color=product_data.get("color"),
                type=product_data.get("type"),
                price=product_data.get("price"),
                description=product_data.get("description"),
                images=product_data.get("images", []),
                link=product_data.get("link"),
                search_query=product_data.get("search_query"),
                created_at=created_at
            )
            products.append(product)
        
        logger_service.success(f"Found {len(products)} products matching query '{query}'")
        
        return SearchProductsResponse(
            query=query,
            products=products,
            total_count=total_count,
            page=page,
            page_size=page_size,
            success=True
        )
        
    except Exception as e:
        logger_service.error(f"Failed to search products: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to search products: {str(e)}")

# ============================================================================
# LIKE/DISLIKE ENDPOINTS
# ============================================================================

@router.post("/products/{product_id}/like", response_model=LikeProductResponse)
async def like_product(
    product_id: str,
    current_user: User = Depends(get_current_user),
) -> LikeProductResponse:
    """
    Like a product for the current user.
    
    This endpoint allows users to express their preference for a product.
    If the product is already liked by the user, it will return success without duplicating the like.
    
    Args:
        product_id: ID of the product to like
        current_user: Authenticated user who is liking the product
        
    Returns:
        LikeProductResponse: Success status with like information
        
    Raises:
        HTTPException: If product not found or like operation fails
    """
    try:
        # Use the database service to handle the like operation
        result = database_service.like_product(user_id=current_user.id, product_id=product_id)
        
        if result["success"]:
            return LikeProductResponse(
                success=True,
                message=result["message"],
                product_id=product_id,
                is_liked=True
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=result["message"]
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to like product: {str(e)}"
        )


@router.post("/products/{product_id}/dislike", response_model=LikeProductResponse)
async def dislike_product(
    product_id: str,
    current_user: User = Depends(get_current_user),
) -> LikeProductResponse:
    """
    Unlike (remove like from) a product for the current user.
    
    This endpoint allows users to remove their like from a product they previously liked.
    If the product is not currently liked by the user, it will return success without error.
    
    Args:
        product_id: ID of the product to unlike
        current_user: Authenticated user who is unliking the product
        
    Returns:
        LikeProductResponse: Success status with unlike information
        
    Raises:
        HTTPException: If product not found or unlike operation fails
    """
    try:
        # Use the database service to handle the unlike operation
        result = database_service.dislike_product(user_id=current_user.id, product_id=product_id)
        
        if result["success"]:
            return LikeProductResponse(
                success=True,
                message=result["message"],
                product_id=product_id,
                is_liked=False
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=result["message"]
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to unlike product: {str(e)}"
        )


@router.get("/products/liked", response_model=ProductsResponse)
async def get_liked_products(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    current_user: User = Depends(get_current_user)
) -> ProductsResponse:
    """
    Get all products that the current user has liked with pagination.
    
    Args:
        page: Page number (starting from 1)
        page_size: Number of products per page (max 100)
        current_user: Authenticated user
        
    Returns:
        ProductsResponse: List of user's liked products with pagination info
        
    Raises:
        HTTPException: If database operation fails
    """
    try:
        logger_service.info(f"Fetching liked products for user {current_user.id} - Page: {page}, Size: {page_size}")

        result = database_service.get_liked_products(
            user_id=current_user.id,
            page=page,
            page_size=page_size
        )
        
        products = []
        for product_data in result["products"]:
            # Parse created_at if it exists
            created_at = None
            if product_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(product_data["created_at"].replace('Z', '+00:00'))
                except:
                    created_at = None

            product = LikedProductResponse(
                id=product_data["id"],
                title=product_data.get("title"),
                brand=product_data.get("brand"),
                type=product_data.get("type"),
                price=product_data.get("price"),
                description=product_data.get("description"),
                images=product_data.get("images", []),
                link=product_data.get("link"),
                search_query=product_data.get("search_query"),
                style=product_data.get("style"),
                color=product_data.get("color"),
                points=product_data.get("points"),
                created_at=created_at,
                is_liked=True
            )
            products.append(product)

        return ProductsResponse(
            products=products,
            total_count=result["total_count"],
            page=result["page"],
            page_size=result["page_size"],
            success=True
        )
        
    except Exception as e:
        logger_service.error(f"Failed to retrieve liked products: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve liked products: {str(e)}"
        )

