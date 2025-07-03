# filepath: c:\Users\rodri\Desktop\projects\pierre\pierre-back\routes\outfits.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import uuid

from utils.models import User
from utils.auth import get_current_user
from services.db import get_database_service, DatabasePaginatedResponse, DatabaseSimilarityResponse, DatabaseLikeResponse, DatabaseOutfit, DatabaseProduct, DatabaseService
from services.logger import get_logger_service

# Create router for outfit endpoints
router = APIRouter()
logger_service = get_logger_service()

# ============================================================================
# PYDANTIC MODELS FOR REQUEST/RESPONSE
# ============================================================================

class OutfitCreateRequest(BaseModel):
    """Request model for creating a new outfit"""
    title: str
    description: str
    image_url: str
    user_prompt: str
    style: str
    points: int
    products: List[str]

class OutfitSearchRequest(BaseModel):
    """Request model for searching outfits"""
    query: str
    page: int = 1
    page_size: int = 10

class OutfitResponse(BaseModel):
    """Response model for outfit data"""
    id: int
    name: str
    description: str
    image_url: str
    user_prompt: str
    products: Optional[List[Dict[str, Any]]] = None
    style: str
    points: int

class ListOutfitResponse(BaseModel):
    """Response model for outfit listings"""
    outfits: List[OutfitResponse]
    total_count: int
    page: int
    page_size: int
    success: bool = True

class LikeOutfitResponse(BaseModel):
    """Response model for outfit like/unlike operations"""
    success: bool
    message: str
    outfit_id: int
    is_liked: bool

class OperationOutfitResponse(BaseModel):
    """Response model for outfit operations (create, update, delete)"""
    success: bool
    message: str
    outfit_id: Optional[int] = None

# ============================================================================
# CRUD ENDPOINTS
# ============================================================================

@router.get("/outfits/", response_model=DatabasePaginatedResponse[DatabaseOutfit])
async def get_outfits(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    include_products: bool = Query(False, description="Include associated products in the response"),
    include_likes: bool = Query(True, description="Include like counts in the response"),
    current_user: User = Depends(get_current_user), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabasePaginatedResponse[DatabaseOutfit]:
    """
    Get all outfits with pagination.
    
    Args:
        page: Page number (starting from 1)
        page_size: Number of outfits per page (max 100)
        include_products: Whether to include associated products in the response
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        ListOutfitResponse: List of outfits with pagination info
        
    Raises:
        HTTPException: If database operation fails
    """
    try:
        logger_service.info(f"Retrieving outfits with pagination: page={page}, page_size={page_size}, include_products={include_products}")

        if include_products:
            result: DatabasePaginatedResponse = await database_service.get_outfits_with_products(
                user_id=current_user.id,
                page=page,
                page_size=page_size,
                include_likes=include_likes
            )
        else:
            result: DatabasePaginatedResponse = await database_service.get_outfits(
                user_id=current_user.id,
                page=page,
                page_size=page_size,
                include_likes=include_likes
            )
        
        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve outfits: {str(e)}"
        )

@router.get("/outfits/liked", response_model=DatabasePaginatedResponse[DatabaseOutfit])
async def get_liked_outfits(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    include_products: bool = Query(False, description="Include associated products in the response"),
    current_user: User = Depends(get_current_user),
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabasePaginatedResponse[DatabaseOutfit]:
    """
    Get all outfits that the current user has liked with pagination.
    
    Args:
        page: Page number (starting from 1)
        page_size: Number of outfits per page (max 100)
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        ListOutfitResponse: List of user's liked outfits with pagination info
        
    Raises:
        HTTPException: If database operation fails
    """
    try:
        if include_products:
            result: DatabasePaginatedResponse[DatabaseOutfit] = await database_service.get_liked_outfits_with_products(
                user_id=current_user.id,
                page=page,
                page_size=page_size,
            )
        else:
            result: DatabasePaginatedResponse[DatabaseOutfit] = await database_service.get_liked_outfits(
                user_id=current_user.id,
                page=page,
                page_size=page_size,
            )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve liked outfits: {str(e)}"
        )

@router.get("/outfits/search", response_model=DatabasePaginatedResponse[DatabaseOutfit])
async def search_outfits(
    query: str = Query(..., description="Search query for outfits"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, description="Number of items per page"),
    current_user: User = Depends(get_current_user), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabasePaginatedResponse[DatabaseOutfit]:
    """
    Search outfits based on title, description, and user prompt.
    
    This endpoint performs a text search across outfit titles, descriptions, and user prompts
    to find outfits that match the user's search query. The search is case-insensitive and
    supports partial matching.
    
    Args:
        query: Search query string to match against outfit content
        page: Page number (starting from 1)
        page_size: Number of outfits per page (max 100)
        current_user: Authenticated user
        
    Returns:
        DatabasePaginatedResponse: List of matching outfits with pagination info
        
    Raises:
        HTTPException: If database operation fails or query is invalid
    """
    try:
        logger_service.info(f"Searching outfits with query: {query}, page: {page}, page_size: {page_size}")

        result = await database_service.search_outfits(
            query=query,
            page=page,
            page_size=page_size
        )

        if not result.success:
            raise HTTPException(
                status_code=500,
                detail="Failed to search outfits"
            )

        logger_service.success(f"Found {len(result.data)} outfits matching query '{query}'")
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
            detail=f"Failed to search outfits: {str(e)}"
        )

@router.get("/outfits/{outfit_id}", response_model=Optional[DatabaseOutfit])
async def get_outfit(
    outfit_id: int,
    include_products: bool = Query(False, description="Include associated products in the response"),
    include_likes: bool = Query(True, description="Include like counts in the response"),
    current_user: User = Depends(get_current_user), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
) -> Optional[DatabaseOutfit]:
    """
    Get a specific outfit by ID with all associated products.
    
    Args:
        outfit_id: ID of the outfit to retrieve
        current_user: Authenticated user        
    Returns:
        OutfitResponse: Outfit data with associated products
        
    Raises:
        HTTPException: If outfit not found or database operation fails
    """
    try:

        logger_service.info(f"Retrieving outfit with ID: {outfit_id}, include_products: {include_products}")

        if include_products:
            outfit_data: DatabaseOutfit = await database_service.get_outfit_with_products(outfit_id, user_id=current_user.id, include_likes=include_likes)
        else:
            outfit_data: DatabaseOutfit = await database_service.get_outfit(outfit_id, user_id=current_user.id, include_likes=include_likes)

        if not outfit_data:
            raise HTTPException(
                status_code=404,
                detail=f"Outfit with ID {outfit_id} not found"
            )

        return outfit_data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve outfit: {str(e)}"
        )

@router.post("/outfits/", response_model=OperationOutfitResponse)
async def create_outfit(
    request: OutfitCreateRequest,
    current_user: User = Depends(get_current_user), # just to ensure user is authenticated
    database_service: DatabaseService = Depends(get_database_service)
) -> OperationOutfitResponse:
    """
    Create a new outfit.
    
    Args:
        request: Outfit creation data
        current_user: Authenticated user
        
    Returns:
        OperationOutfitResponse: Success status and outfit ID
        
    Raises:
        HTTPException: If creation fails
    """
    try:
        # Create DatabaseOutfit object
        outfit = DatabaseOutfit(
            title=request.title,
            description=request.description,
            image_url=request.image_url,
            user_prompt=request.user_prompt
        )
        
        # Get products if provided
        products = []
        if request.products:
            # Retrieve product data for the provided IDs
            for product_id in request.products:
                product_result = database_service.supabase.table("products").select(
                    "*"
                ).eq("id", product_id).execute()
                
                if product_result.data:
                    product_data = product_result.data[0]
                    products.append(DatabaseProduct(
                        id=product_data["id"],
                        type=product_data.get("type"),
                        search_query=product_data.get("search_query"),
                        link=product_data.get("link"),
                        title=product_data.get("title"),
                        price=product_data.get("price"),
                        images=product_data.get("images"),
                        brand=product_data.get("brand"),
                        description=product_data.get("description")
                    ))
        
        # Insert outfit with products
        result = database_service.insert_outfit_with_products(outfit, products)
        
        if result["success"]:
            return OperationOutfitResponse(
                success=True,
                message=result["message"],
                outfit_id=result["outfit_id"]
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
            detail=f"Failed to create outfit: {str(e)}"
        )

# ============================================================================
# LIKE/DISLIKE ENDPOINTS
# ============================================================================

@router.post("/outfits/{outfit_id}/like", response_model=DatabaseLikeResponse)
async def like_outfit(
    outfit_id: int,
    current_user: User = Depends(get_current_user),
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabaseLikeResponse:
    """
    Like an outfit for the current user.
    
    This endpoint allows users to express their preference for an outfit.
    If the outfit is already liked by the user, it will return success without duplicating the like.
    
    Args:
        outfit_id: ID of the outfit to like
        current_user: Authenticated user who is liking the outfit
        
    Returns:
        DatabaseLikeResponse: Success status with like information
        
    Raises:
        HTTPException: If outfit not found or like operation fails
    """
    try:
        # Use the database service to handle the like operation
        result: DatabaseLikeResponse = await database_service.like_outfit(user_id=current_user.id, outfit_id=outfit_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to like outfit: {str(e)}"
        )

@router.post("/outfits/{outfit_id}/dislike", response_model=DatabaseLikeResponse)
async def dislike_outfit(
    outfit_id: int,
    current_user: User = Depends(get_current_user),
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabaseLikeResponse:
    """
    Unlike (remove like from) an outfit for the current user.
    
    This endpoint allows users to remove their like from an outfit they previously liked.
    If the outfit is not currently liked by the user, it will return success without error.
    
    Args:
        outfit_id: ID of the outfit to unlike
        current_user: Authenticated user who is unliking the outfit
        
    Returns:
        DatabaseLikeResponse: Success status with unlike information
        
    Raises:
        HTTPException: If outfit not found or unlike operation fails
    """
    try:
        result: DatabaseLikeResponse = await database_service.dislike_outfit(user_id=current_user.id, outfit_id=outfit_id)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to unlike outfit: {str(e)}"
        )

# ============================================================================
# SIMILARITY ENDPOINTS
# ============================================================================

@router.get("/outfits/{outfit_id}/similar", response_model=DatabaseSimilarityResponse[DatabaseOutfit])
async def get_similar_outfits(
    outfit_id: int,
    limit: int = Query(10, ge=1, le=50, description="Maximum number of similar outfits to return"),
    threshold: float = Query(0.7, ge=0.1, le=1.0, description="Minimum similarity threshold (0.1-1.0)"),
    current_user: User = Depends(get_current_user),
    database_service: DatabaseService = Depends(get_database_service)
) -> DatabaseSimilarityResponse[DatabaseOutfit]:
    """
    Find outfits similar to the given outfit based on semantic analysis of user prompts.
    
    This endpoint uses advanced AI embeddings to analyze the semantic meaning of outfit prompts
    and find genuinely similar outfits, rather than simple text matching. It compares the target
    outfit's user prompt against all other outfit prompts in the database.
    
    Args:
        outfit_id: ID of the target outfit to find similarities for
        limit: Maximum number of similar outfits to return (1-50, default: 10)
        threshold: Minimum similarity score to include (0.1-1.0, default: 0.7)
        current_user: Authenticated user
          Returns:
        DatabaseSimilarityResponse[DatabaseOutfit]: Target outfit info and list of similar outfits with similarity scores
        
    Raises:
        HTTPException: If outfit not found, API fails, or other errors occur
        
    Example:
        GET /api/outfits/123/similar?limit=5&threshold=0.8
        
        Returns outfits with prompts semantically similar to outfit 123's prompt,
        with at least 80% similarity, limited to 5 results.
    """
    try:
        logger_service.info(
            f"Finding similar outfits for outfit {outfit_id} "
            f"(limit: {limit}, threshold: {threshold})"
        )
        
        # Use the database service to find similar outfits
        result: DatabaseSimilarityResponse[DatabaseOutfit] = await database_service.find_similar_outfits(
            outfit_id=outfit_id,
            limit=limit,
            threshold=threshold
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to find similar outfits for outfit {outfit_id}: {str(e)}"
        logger_service.error(error_msg)
        raise HTTPException(
            status_code=500,
            detail=error_msg
        )

