from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import uuid
from services.stylist import StylistService, Outfit
from services.db import get_database_service, DatabaseService, DatabaseOutfit, DatabaseProduct
from utils.models import User
from utils.auth import get_current_user
from services.image import get_image_service
from services.logger import get_logger_service
from services.auth import get_auth_service

# Create router for stylist endpoints
router = APIRouter()

# Initialize auth service
auth_service = get_auth_service()
logger_service = get_logger_service()
image_service = get_image_service()

class CreateOutfitResponse(BaseModel):
    user_prompt: str
    outfits: List[Outfit] = []
    success: bool = True

class CreateOutfitRequest(BaseModel):
    prompt: str


def _convert_outfit_to_database_models(outfit: Outfit):
    """
    Convert an OutfitConcept to DatabaseOutfit and DatabaseProduct models.
    
    Args:
        outfit: The generated OutfitConcept from the stylist service
        user_prompt: The original user prompt that generated this outfit
        
    Returns:
        Tuple of (DatabaseOutfit, List[DatabaseProduct])
    """
    # Create the database outfit model
    db_outfit = DatabaseOutfit(
        title=outfit.name,
        description=outfit.description,
        image_url=outfit.image_url,  # TODO: No image URL available in current outfit concept
        user_prompt=outfit.user_prompt,
        points=outfit.points
    )
    
    # Create database product models from outfit items
    db_products = []
    for product in outfit.products:
        if product:  # Only include items that have associated products            
            db_product = DatabaseProduct(
                id=product.id,
                type=product.type,
                search_query=product.search_query,
                points=product.points,
                color=product.color,
                link=getattr(product, 'link', None),
                title=getattr(product, 'title', None),
                price=getattr(product, 'price', 0.0),
                images=getattr(product, 'images', []),
                brand=getattr(product, 'brand', None),
                description=getattr(product, 'description', None)
            )
            db_products.append(db_product)
    
    return db_outfit, db_products

@router.post("/stylist/outfit", response_model=CreateOutfitResponse)
async def create_outfit(
    request: CreateOutfitRequest, 
    user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
):
    try:
        logger_service.info(f"Generating outfit for user: {user.id} with prompt: {request.prompt}")
        logger_service.debug(f"Provided user data: {user.model_dump()}")

        # Create stylist service context from user data
        stylist_service = StylistService(user=user, user_prompt=request.prompt)
        outfit: Outfit = await stylist_service.run()

        logger_service.success(f"Generated outfit: {outfit.name} with {len(outfit.products)} products")

        logger_service.info(f"Generating outfit image for: {outfit.name}")
        outfit_image = image_service.generate_image(outfit)
        outfit.image_url = outfit_image
        logger_service.success(f"Outfit image generated: {outfit_image}") 

        # Convert outfit concept to database models
        db_outfit, db_products = _convert_outfit_to_database_models(outfit)
        logger_service.info(f"Saving outfit '{db_outfit.title}' with {len(db_products)} products to database")

        # Save to database
        save_result = db_service.insert_outfit_with_products(db_outfit, db_products)

        if save_result['success'] is False:
            logger_service.error(f"Failed to save outfit '{db_outfit.title}' to database: {save_result['error']}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save outfit: {save_result['error']}"
            )

        logger_service.success(f"Outfit '{db_outfit.title}' saved to database with ID: {save_result['outfit_id']}")
        return CreateOutfitResponse(
            user_prompt=request.prompt,
            outfits=[outfit],
            success=True
        )

    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Failed to create outfit: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create outfit: {str(e)}"
        )
