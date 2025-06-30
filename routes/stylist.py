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
database_service = get_database_service()

class CreateOutfitResponse(BaseModel):
    user_prompt: str
    outfits: List[Outfit] = []
    success: bool = True

class CreateOutfitRequest(BaseModel):
    prompt: str
    number_of_outfits: Optional[int] = 1


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
        name=outfit.name,
        description=outfit.description,
        image_url=outfit.image_url,
        user_prompt=outfit.user_prompt,
        points=outfit.points,
        style=outfit.style,
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
                link=product.link,
                title=product.title,
                price=product.price,
                images=product.images,
                brand=product.brand,
                description=product.description,
                style=product.style
            )
            db_products.append(db_product)
    
    return db_outfit, db_products

def _generate_outfit_image(outfit: Outfit) -> str:
    """
    Generate an image for the given outfit concept.
    
    Args:
        outfit: The generated OutfitConcept from the stylist service
        
    Returns:
        URL of the generated outfit image
    """
    logger_service.info(f"Generating outfit image for: {outfit.name}")
    outfit_image = image_service.generate_image(outfit)
    logger_service.success(f"Outfit image generated: {outfit_image}")
    return outfit_image

def _save_outfit_to_db(outfit: Outfit) -> str:
    """
    Save the generated outfit to the database.
    
    Args:
        outfit: The generated OutfitConcept from the stylist service
        
    Returns:
        Dictionary with success status and outfit ID
    """
    db_outfit, db_products = _convert_outfit_to_database_models(outfit)
    logger_service.info(f"Saving outfit '{db_outfit.name}' with {len(db_products)} products to database")
    
    save_result = database_service.insert_outfit_with_products(db_outfit, db_products)
    
    if not save_result['success']:
        logger_service.error(f"Failed to save outfit '{db_outfit.name}' to database: {save_result['error']}")
        return {'success': False, 'error': save_result['error']}
    
    logger_service.success(f"Outfit '{db_outfit.name}' saved to database with ID: {save_result['outfit_id']}")
    return save_result['outfit_id']

@router.post("/stylist/outfit", response_model=CreateOutfitResponse)
async def create_outfit(
    request: CreateOutfitRequest, 
    user: User = Depends(get_current_user),
):
    try:
        logger_service.info(f"Generating outfit for user: {user.id} with prompt: {request.prompt} and number of outfits: {request.number_of_outfits}")
        logger_service.debug(f"Provided user data: {user.model_dump()}")

        # Create stylist service context from user data
        stylist_service = StylistService(user=user, user_prompt=request.prompt)
        outfit: Outfit = await stylist_service.run()
        logger_service.success(f"Generated outfit: {outfit.name} with {len(outfit.products)} products")

        outfit.image_url = _generate_outfit_image(outfit)

        # Convert outfit concept to database models
        db_outfit, db_products = _convert_outfit_to_database_models(outfit)
        logger_service.info(f"Saving outfit '{db_outfit.name}' with {len(db_products)} products to database")

        # Save to database
        outfit_id = _save_outfit_to_db(outfit)
        outfit.id = outfit_id

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
