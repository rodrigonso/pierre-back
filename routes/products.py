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
    brand: Optional[str] = Query(None, description="Filter products by brand name"),
    type: Optional[str] = Query(None, description="Filter products by type"),
    auth = Depends(verify_token), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
):
    """
    Get all products with pagination and optional filtering.
    
    Returns a paginated list of all products in the database.
    Supports filtering by product type and brand.
    
    Args:
        page: Page number (starting from 1)
        page_size: Number of products per page (max 100)
        include_likes: Include user likes information in response
        brand: Optional filter by brand name (case-insensitive)
        type: Optional filter by product type (case-insensitive)
        
    Returns:
        DatabasePaginatedResponse[DatabaseProduct]: Paginated list of products
        
    Raises:
        HTTPException: If database operation fails
    """
    try:
        user_id = auth.get("user_id")
        logger_service.info(f"Fetching products - Page: {page}, Size: {page_size}, Brand: {brand}, Type: {type}")
        
        result: DatabasePaginatedResponse[DatabaseProduct] = await database_service.get_products(
            page=page,
            page_size=page_size,
            user_id=user_id,
            include_likes=include_likes,
            brand=brand,
            type=type
        )

        return result

    except Exception as e:
        logger_service.error(f"Failed to retrieve products: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve products: {str(e)}")

@router.get("/products/search/", response_model=DatabasePaginatedResponse[DatabaseProduct])
async def search_products(
    query: str = Query(..., description="Search query for products"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, description="Number of items per page"),
    brand: Optional[str] = Query(None, description="Filter products by brand name"),
    type: Optional[str] = Query(None, description="Filter products by type"),
    auth = Depends(verify_token), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabasePaginatedResponse[DatabaseProduct]:
    """
    Search products using PostgreSQL ilike operator on the search_query column.
    
    This endpoint performs a case-insensitive text search using PostgreSQL's ilike operator
    on the search_query column, allowing for pattern matching and partial text searches.
    Can be combined with brand and type filters for more refined search results.
    
    Args:
        query: Search query string to match against product search_query column
        page: Page number (starting from 1)
        page_size: Number of products per page (max 100)
        brand: Optional filter by brand name (case-insensitive)
        type: Optional filter by product type (case-insensitive)
        
    Returns:
        DatabasePaginatedResponse: List of matching products with pagination info
        
    Raises:
        HTTPException: If database operation fails or query is invalid
    """
    try:
        logger_service.info(f"Searching products using ilike for query: '{query}', page: {page}, page_size: {page_size}, brand: {brand}, type: {type}")

        result = await database_service.search_products(
            query=query,
            page=page,
            page_size=page_size,
            brand=brand,
            type=type
        )

        if not result.success:
            raise HTTPException(
                status_code=500,
                detail="Failed to search products"
            )

        logger_service.success(f"Found {len(result.data)} products matching query '{query}'")
        return result

    except ValueError as e:
        # Handle validation errors from the database service
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search products: {str(e)}"
        )

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

