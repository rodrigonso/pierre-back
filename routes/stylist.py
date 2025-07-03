from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import uuid
import asyncio
from services.stylist import StylistService, Outfit, Product
from services.db import get_database_service, DatabaseService, DatabaseOutfit, DatabaseProduct
from utils.models import User
from utils.auth import get_current_user
from services.image import get_image_service
from services.logger import get_logger_service
from services.auth import get_auth_service
from utils.helpers import SearchProduct

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
    cancelled: Optional[bool] = None

class CreateOutfitRequest(BaseModel):
    prompt: str
    number_of_outfits: Optional[int] = 1

class StylistRequest(BaseModel):
    prompt: str

class StylistResponse(BaseModel):
    user_prompt: str
    intent: str
    result: str
    success: bool = True
    data: List[Outfit | Product] = []


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

async def _generate_outfit_image(outfit: Outfit) -> str:
    """
    Generate an image for the given outfit concept.
    
    Args:
        outfit: The generated OutfitConcept from the stylist service
        
    Returns:
        URL of the generated outfit image
    """
    logger_service.info(f"Generating outfit image for: {outfit.name}")
    outfit_image = await image_service.generate_image(outfit)
    logger_service.success(f"Outfit image generated: {outfit_image}")
    return outfit_image

async def _save_outfit_to_db(outfit: Outfit, database_service: DatabaseService) -> str:
    """
    Save the generated outfit to the database.
    
    Args:
        outfit: The generated OutfitConcept from the stylist service
        
    Returns:
        Dictionary with success status and outfit ID
    """
    db_outfit, db_products = _convert_outfit_to_database_models(outfit)
    logger_service.info(f"Saving outfit '{db_outfit.name}' with {len(db_products)} products to database")
    
    save_result = await database_service.insert_outfit_with_products(db_outfit, db_products)
    
    if not save_result['success']:
        logger_service.error(f"Failed to save outfit '{db_outfit.name}' to database: {save_result['error']}")
        return {'success': False, 'error': save_result['error']}
    
    logger_service.success(f"Outfit '{db_outfit.name}' saved to database with ID: {save_result['outfit_id']}")
    return save_result['outfit_id']

@router.post("/stylist/outfit", response_model=CreateOutfitResponse)
async def create_outfit(
    request: CreateOutfitRequest, 
    user: User = Depends(get_current_user),
    database_service: DatabaseService = Depends(get_database_service)
):
    try:
        logger_service.info(f"Generating outfit for user: {user.id} with prompt: {request.prompt} and number of outfits: {request.number_of_outfits}")
        logger_service.debug(f"Provided user data: {user.model_dump()}")
        stylist_service = StylistService(user=user, user_prompt=request.prompt)
        
        try:
            outfit: Outfit = await stylist_service.generate_outfit()
            logger_service.success(f"Generated outfit: {outfit.name} with {len(outfit.products)} products")

        except asyncio.CancelledError:
            logger_service.warning(f"Outfit generation cancelled for user: {user.id}")
            return CreateOutfitResponse(
                user_prompt=request.prompt,
                outfits=[],
                success=False,
                cancelled=True
            )

        outfit.image_url = await _generate_outfit_image(outfit)

        # Convert outfit concept to database models
        db_outfit, db_products = _convert_outfit_to_database_models(outfit)
        logger_service.info(f"Saving outfit '{db_outfit.name}' with {len(db_products)} products to database")

        # Save to database
        outfit_id = await _save_outfit_to_db(outfit, database_service)
        outfit.id = outfit_id

        return CreateOutfitResponse(
            user_prompt=request.prompt,
            outfits=[outfit],
            success=True
        )

    except HTTPException:
        raise
    except asyncio.CancelledError:
        # Handle cancellation at the top level as well (in case it happens during other operations)
        logger_service.warning(f"Request cancelled for user: {user.id}")
        return CreateOutfitResponse(
            user_prompt=request.prompt,
            outfits=[],
            success=False,
            cancelled=True
        )
    except Exception as e:
        logger_service.error(f"Failed to create outfit: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create outfit: {str(e)}"
        )

@router.post("/stylist/request", response_model=StylistResponse)
async def stylist_request(
    request: StylistRequest, 
    user: User = Depends(get_current_user),
    database_service: DatabaseService = Depends(get_database_service)
):
    """
    Intelligent stylist endpoint that determines user intent and routes to appropriate method.
    
    This endpoint analyzes the user's prompt to determine whether they want:
    - A complete outfit generated (generate_outfit)
    - Specific products found (generate_products)
    
    Args:
        request: StylistRequest containing the user's prompt
        user: Authenticated user
        database_service: Database service for saving results
        
    Returns:
        StylistResponse: Contains intent classification and results
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        logger_service.info(f"Processing intelligent stylist request for user: {user.id} with prompt: {request.prompt}")
        logger_service.debug(f"Provided user data: {user.model_dump()}")
        stylist_service = StylistService(user=user, user_prompt=request.prompt)
        
        # First, determine the user's intent
        intent = await stylist_service.determine_user_intent()
        logger_service.info(f"Determined user intent: {intent}")
        
        # Route to appropriate method based on intent
        if intent == "generate_outfit":
            logger_service.info("Routing to outfit generation")
            outfit = await stylist_service.generate_outfit()
            
            # Generate image for the outfit
            outfit.image_url = await _generate_outfit_image(outfit)
            
            # Save to database
            outfit_id = await _save_outfit_to_db(outfit, database_service)
            outfit.id = outfit_id
            
            return StylistResponse(
                user_prompt=request.prompt,
                intent=intent,
                result=f"Successfully generated outfit: {outfit.name}",
                success=True,
                data=[outfit],
            )
    
        elif intent == "find_products":
            logger_service.info("Routing to product search")
            products: List[Product] = await stylist_service.search_for_products()
            
            return StylistResponse(
                user_prompt=request.prompt,
                intent=intent,
                result=f"Found {len(products)} products matching your request",
                success=True,
                data=products
            )
            
        else:
            # Fallback to outfit generation for unclear intent
            logger_service.error(f"Unclear intent '{intent}', defaulting to outfit generation")

            return StylistResponse(
                user_prompt=request.prompt,
                intent="unknown",
                result=f"error: Unclear intent '{intent}'",
                success=True,
                data=[]
            )

    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Failed to process stylist request: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process stylist request: {str(e)}"
        )

