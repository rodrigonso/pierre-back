from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import datetime
import uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from utils.models import User
from utils.auth import verify_token
from services.db import get_database_service, DatabasePaginatedResponse, DatabaseProduct, DatabaseLikeResponse, DatabaseService
from services.logger import get_logger_service

# Create router for product endpoints
router = APIRouter()
logger_service = get_logger_service()

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

@router.get("/products/", response_model=DatabasePaginatedResponse[DatabaseProduct])
async def get_products(
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of products per page"),
    include_likes: bool = Query(True, description="Include user likes in response"),
    auth = Depends(verify_token), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
):
    """
    Get all products with pagination and optional filtering.
    
    Returns a paginated list of all products in the database.
    Supports filtering by product type and brand.
    """
    try:
        user_id = auth.get("user_id")
        logger_service.info(f"Fetching products - Page: {page}, Size: {page_size}")
        
        result: DatabasePaginatedResponse[DatabaseProduct] = await database_service.get_products(
            page=page,
            page_size=page_size,
            user_id=user_id,
            include_likes=include_likes
        )

        return result

    except Exception as e:
        logger_service.error(f"Failed to retrieve products: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve products: {str(e)}")

@router.get("/products/search/", response_model=SearchProductsResponse)
async def search_products(
    query: str = Query(..., description="Search query for products"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, description="Number of items per page"),
    auth = Depends(verify_token), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
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
        result = await search_query.order("created_at", desc=True).range(
            offset, offset + page_size - 1
        ).execute()
        
        # Get total count for pagination (with same search conditions)
        count_query = database_service.supabase.table("products").select("id", count="exact")
        count_query = count_query.or_(search_conditions)
        
        count_result = await count_query.execute()
        total_count = count_result.count if count_result.count else 0
        
        # Convert results to ProductData models
        products = []
        for product_data in result.data:
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

@router.post("/products/{product_id}/like", response_model=DatabaseLikeResponse)
async def like_product(
    product_id: str,
    auth = Depends(verify_token), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabaseLikeResponse:
    """
    Like a product for the current user.
    
    This endpoint allows users to express their preference for a product.
    If the product is already liked by the user, it will return success without duplicating the like.
    
    Args:
        product_id: ID of the product to like
        current_user: Authenticated user who is liking the product
        
    Returns:
        DatabaseLikeResponse: Success status with like information

    Raises:
        HTTPException: If product not found or like operation fails
    """
    try:
        user_id = auth.get("user_id")
        # Use the database service to handle the like operation
        result: DatabaseLikeResponse = await database_service.like_product(user_id=user_id, product_id=product_id)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to like product: {str(e)}"
        )


@router.post("/products/{product_id}/dislike", response_model=DatabaseLikeResponse)
async def dislike_product(
    product_id: str,
    auth = Depends(verify_token), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabaseLikeResponse:
    """
    Unlike (remove like from) a product for the current user.
    
    This endpoint allows users to remove their like from a product they previously liked.
    If the product is not currently liked by the user, it will return success without error.
    
    Args:
        product_id: ID of the product to unlike
        current_user: Authenticated user who is unliking the product
        
    Returns:
        DatabaseLikeResponse: Success status with unlike information

    Raises:
        HTTPException: If product not found or unlike operation fails
    """
    try:
        user_id = auth.get("user_id")
        # Use the database service to handle the unlike operation
        result: DatabaseLikeResponse = await database_service.dislike_product(user_id=user_id, product_id=product_id)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to unlike product: {str(e)}"
        )


@router.get("/products/liked", response_model=DatabasePaginatedResponse[DatabaseProduct])
async def get_liked_products(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    auth = Depends(verify_token),
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabasePaginatedResponse[DatabaseProduct]:
    """
    Get all products that the current user has liked with pagination.
    
    Args:
        page: Page number (starting from 1)
        page_size: Number of products per page (max 100)
        current_user: Authenticated user
        
    Returns:
        DatabasePaginatedResponse[DatabaseProduct]: List of user's liked products with pagination info
        
    Raises:
        HTTPException: If database operation fails
    """
    try:
        user_id = auth.get("user_id")
        logger_service.info(f"Fetching liked products for user {user_id} - Page: {page}, Size: {page_size}")

        result: DatabasePaginatedResponse[DatabaseProduct] = await database_service.get_liked_products(
            user_id=user_id,
            page=page,
            page_size=page_size
        )
        
        return result
        
    except Exception as e:
        logger_service.error(f"Failed to retrieve liked products: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve liked products: {str(e)}"
        )

