# filepath: c:\Users\rodri\Desktop\projects\pierre\pierre-back\routes\outfits.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import uuid

from utils.models import User
from utils.auth import get_current_user
from services.db import get_database_service, DatabaseService, DatabaseOutfit, DatabaseProduct

# Create router for outfit endpoints
router = APIRouter()

# ============================================================================
# PYDANTIC MODELS FOR REQUEST/RESPONSE
# ============================================================================

class OutfitCreateRequest(BaseModel):
    """Request model for creating a new outfit"""
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    user_prompt: Optional[str] = None
    products: Optional[List[str]] = []  # List of product IDs to associate

class OutfitUpdateRequest(BaseModel):
    """Request model for updating an existing outfit"""
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    user_prompt: Optional[str] = None

class OutfitResponse(BaseModel):
    """Response model for outfit data"""
    id: int
    title: Optional[str]
    description: Optional[str]
    image_url: Optional[str]
    user_prompt: Optional[str]
    created_at: datetime
    products: Optional[List[Dict[str, Any]]] = []

class OutfitListResponse(BaseModel):
    """Response model for outfit listings"""
    outfits: List[OutfitResponse]
    total_count: int
    page: int
    page_size: int
    success: bool = True

class OutfitOperationResponse(BaseModel):
    """Response model for outfit operations (create, update, delete)"""
    success: bool
    message: str
    outfit_id: Optional[int] = None

class OutfitLikeResponse(BaseModel):
    """Response model for outfit like/unlike operations"""
    success: bool
    message: str
    outfit_id: int
    is_liked: bool

# ============================================================================
# CRUD ENDPOINTS
# ============================================================================

@router.get("/outfits/", response_model=OutfitListResponse)
async def get_all_outfits(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitListResponse:
    """
    Get all outfits with pagination.
    
    Args:
        page: Page number (starting from 1)
        page_size: Number of outfits per page (max 100)
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        OutfitListResponse: List of outfits with pagination info
        
    Raises:
        HTTPException: If database operation fails
    """
    try:
        # Calculate offset for pagination
        offset = (page - 1) * page_size
        
        # Get outfits with pagination
        outfits_result = db_service.supabase.table("outfits").select(
            "*"
        ).order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
        
        # Get total count for pagination
        count_result = db_service.supabase.table("outfits").select(
            "id", count="exact"
        ).execute()
        
        total_count = count_result.count if count_result.count else 0
        
        # Convert to response format
        outfit_responses = []
        for outfit in outfits_result.data:
            # Get associated products for each outfit
            outfit_with_products = db_service.get_outfit_with_products(outfit["id"])
            products = outfit_with_products.get("products", []) if outfit_with_products else []
            
            outfit_responses.append(OutfitResponse(
                id=outfit["id"],
                title=outfit.get("title"),
                description=outfit.get("description"),
                image_url=outfit.get("image_url"),
                user_prompt=outfit.get("user_prompt"),
                created_at=outfit["created_at"],
                products=products
            ))
        
        return OutfitListResponse(
            outfits=outfit_responses,
            total_count=total_count,
            page=page,
            page_size=page_size
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve outfits: {str(e)}"
        )

@router.get("/outfits/liked", response_model=OutfitListResponse)
async def get_user_liked_outfits(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitListResponse:
    """
    Get all outfits that the current user has liked with pagination.
    
    Args:
        page: Page number (starting from 1)
        page_size: Number of outfits per page (max 100)
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        OutfitListResponse: List of user's liked outfits with pagination info
        
    Raises:
        HTTPException: If database operation fails
    """
    try:
        # Get user's liked outfits using the database service
        result = db_service.get_user_liked_outfits(
            user_id=current_user.id,
            page=page,
            page_size=page_size
        )
        
        # Convert to response format
        outfit_responses = []
        for outfit_data in result["outfits"]:
            # Products are already included in the outfit data
            products = outfit_data.get("products", [])
            
            outfit_responses.append(OutfitResponse(
                id=outfit_data["id"],
                title=outfit_data.get("title"),
                description=outfit_data.get("description"),
                image_url=outfit_data.get("image_url"),
                user_prompt=outfit_data.get("user_prompt"),
                created_at=outfit_data["created_at"],
                products=products
            ))
        
        return OutfitListResponse(
            outfits=outfit_responses,
            total_count=result["total_count"],
            page=result["page"],
            page_size=result["page_size"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve liked outfits: {str(e)}"
        )

@router.get("/outfits/{outfit_id}", response_model=OutfitResponse)
async def get_outfit_by_id(
    outfit_id: int,
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitResponse:
    """
    Get a specific outfit by ID with all associated products.
    
    Args:
        outfit_id: ID of the outfit to retrieve
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        OutfitResponse: Outfit data with associated products
        
    Raises:
        HTTPException: If outfit not found or database operation fails
    """
    try:
        outfit_data = db_service.get_outfit_with_products(outfit_id)
        
        if not outfit_data:
            raise HTTPException(
                status_code=404,
                detail=f"Outfit with ID {outfit_id} not found"
            )
        
        outfit = outfit_data["outfit"]
        products = outfit_data["products"]
        
        return OutfitResponse(
            id=outfit["id"],
            title=outfit.get("title"),
            description=outfit.get("description"),
            image_url=outfit.get("image_url"),
            user_prompt=outfit.get("user_prompt"),
            created_at=outfit["created_at"],
            products=products
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve outfit: {str(e)}"
        )

@router.post("/outfits/", response_model=OutfitOperationResponse)
async def create_outfit(
    request: OutfitCreateRequest,
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitOperationResponse:
    """
    Create a new outfit.
    
    Args:
        request: Outfit creation data
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        OutfitOperationResponse: Success status and outfit ID
        
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
                product_result = db_service.supabase.table("products").select(
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
        result = db_service.insert_outfit_with_products(outfit, products)
        
        if result["success"]:
            return OutfitOperationResponse(
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

@router.put("/outfits/{outfit_id}", response_model=OutfitOperationResponse)
async def update_outfit(
    outfit_id: int,
    request: OutfitUpdateRequest,
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitOperationResponse:
    """
    Update an existing outfit.
    
    Args:
        outfit_id: ID of the outfit to update
        request: Outfit update data
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        OutfitOperationResponse: Success status and message
        
    Raises:
        HTTPException: If outfit not found or update fails
    """
    try:
        # Check if outfit exists
        outfit_check = db_service.supabase.table("outfits").select(
            "id"
        ).eq("id", outfit_id).execute()
        
        if not outfit_check.data:
            raise HTTPException(
                status_code=404,
                detail=f"Outfit with ID {outfit_id} not found"
            )
        
        # Prepare update data (only include non-None values)
        update_data = {}
        if request.title is not None:
            update_data["title"] = request.title
        if request.description is not None:
            update_data["description"] = request.description
        if request.image_url is not None:
            update_data["image_url"] = request.image_url
        if request.user_prompt is not None:
            update_data["user_prompt"] = request.user_prompt
        
        if not update_data:
            return OutfitOperationResponse(
                success=True,
                message="No changes to update",
                outfit_id=outfit_id
            )
        
        # Add updated timestamp
        update_data["updated_at"] = datetime.utcnow().isoformat()
        
        # Perform update
        result = db_service.supabase.table("outfits").update(
            update_data
        ).eq("id", outfit_id).execute()
        
        if result.data:
            return OutfitOperationResponse(
                success=True,
                message=f"Successfully updated outfit {outfit_id}",
                outfit_id=outfit_id
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to update outfit"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update outfit: {str(e)}"
        )

@router.delete("/outfits/{outfit_id}", response_model=OutfitOperationResponse)
async def delete_outfit(
    outfit_id: int,
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitOperationResponse:
    """
    Delete an outfit and all its associated relationships.
    
    Note: This will not delete the associated products as they might be used in other outfits.
    Only the outfit and its relationships in the product_outfit_junction table are removed.
    
    Args:
        outfit_id: ID of the outfit to delete
        current_user: Authenticated user
        db_service: Database service dependency
        
    Returns:
        OutfitOperationResponse: Success status and message
        
    Raises:
        HTTPException: If outfit not found or deletion fails
    """
    try:
        result = db_service.delete_outfit(outfit_id)
        
        if result["success"]:
            return OutfitOperationResponse(
                success=True,
                message=result["message"],
                outfit_id=outfit_id
            )
        else:
            if "not found" in result["message"]:
                raise HTTPException(
                    status_code=404,
                    detail=result["message"]
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
            detail=f"Failed to delete outfit: {str(e)}"
        )

# ============================================================================
# LIKE/DISLIKE ENDPOINTS
# ============================================================================

@router.post("/outfits/{outfit_id}/like", response_model=OutfitLikeResponse)
async def like_outfit(
    outfit_id: int,
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitLikeResponse:
    """
    Like an outfit for the current user.
    
    This endpoint allows users to express their preference for an outfit.
    If the outfit is already liked by the user, it will return success without duplicating the like.
    
    Args:
        outfit_id: ID of the outfit to like
        current_user: Authenticated user who is liking the outfit
        db_service: Database service dependency
        
    Returns:
        OutfitLikeResponse: Success status with like information
        
    Raises:
        HTTPException: If outfit not found or like operation fails
    """
    try:
        # Use the database service to handle the like operation
        result = db_service.like_outfit(user_id=current_user.id, outfit_id=outfit_id)
        
        if result["success"]:
            return OutfitLikeResponse(
                success=True,
                message=result["message"],
                outfit_id=outfit_id,
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
            detail=f"Failed to like outfit: {str(e)}"
        )

@router.post("/outfits/{outfit_id}/dislike", response_model=OutfitLikeResponse)
async def dislike_outfit(
    outfit_id: int,
    current_user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
) -> OutfitLikeResponse:
    """
    Unlike (remove like from) an outfit for the current user.
    
    This endpoint allows users to remove their like from an outfit they previously liked.
    If the outfit is not currently liked by the user, it will return success without error.
    
    Args:
        outfit_id: ID of the outfit to unlike
        current_user: Authenticated user who is unliking the outfit
        db_service: Database service dependency
        
    Returns:
        OutfitLikeResponse: Success status with unlike information
        
    Raises:
        HTTPException: If outfit not found or unlike operation fails
    """
    try:
        # Use the database service to handle the unlike operation
        result = db_service.dislike_outfit(user_id=current_user.id, outfit_id=outfit_id)
        
        if result["success"]:
            return OutfitLikeResponse(
                success=True,
                message=result["message"],
                outfit_id=outfit_id,
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
            detail=f"Failed to unlike outfit: {str(e)}"
        )