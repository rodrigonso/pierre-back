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
from utils.helpers import SearchProduct

# Create router for stylist endpoints
router = APIRouter()

# Initialize auth service
logger_service = get_logger_service()
image_service = get_image_service()

class StylistRequest(BaseModel):
    prompt: str
    number_of_items: Optional[int] = 1

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

async def _generate_single_outfit(stylist_service: StylistService, database_service: DatabaseService, outfit_number: int) -> Outfit:
    """
    Generate a single outfit with image and save to database.
    
    Args:
        stylist_service: The stylist service instance
        database_service: Database service for saving results
        outfit_number: The outfit number for logging purposes
        
    Returns:
        Outfit: Complete outfit with generated image and database ID
        
    Raises:
        Exception: If outfit generation, image generation, or database save fails
    """
    logger_service.info(f"Generating outfit #{outfit_number}")
    
    # Generate the outfit
    outfit = await stylist_service.generate_outfit()
    logger_service.success(f"Generated outfit #{outfit_number}: {outfit.name} with {len(outfit.products)} products")
    
    # Generate image for the outfit
    outfit.image_url = await _generate_outfit_image(outfit)

    if (not outfit.image_url):
        logger_service.error(f"Failed to generate image for outfit #{outfit_number}: {outfit.name}")
        raise Exception(f"Failed to generate image for outfit #{outfit_number}: {outfit.name}")

    # Save to database
    outfit_id = await _save_outfit_to_db(outfit, database_service)
    outfit.id = outfit_id
    
    logger_service.success(f"Completed outfit #{outfit_number}: {outfit.name}")
    return outfit

async def _save_products_to_db(products: List[Product], database_service: DatabaseService) -> List[str]:
    """
    Save a list of products to the database.
    
    Args:
        products: List of Product objects to save
        database_service: Database service for saving results
        
    Returns:
        List of product IDs that were saved
    """
    product_ids = []
    for product in products:
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
        result = await database_service.insert_product(db_product)
        if result['success']:
            product_ids.append(result['product_id'])
        else:
            logger_service.error(f"Failed to save product '{product.title}': {result['error']}")
    
    return product_ids

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
            
            # Determine number of outfits to generate (default to 1)
            num_items = getattr(request, 'number_of_items', 1)
            logger_service.info(f"Generating {num_items} outfit(s) in parallel")

            # Generate multiple outfits in parallel
            outfit_tasks = [
                _generate_single_outfit(stylist_service, database_service, i + 1)
                for i in range(num_items)
            ]
            
            try:
                outfits = await asyncio.gather(*outfit_tasks, return_exceptions=True)
                
                # Filter out any exceptions and collect successful outfits
                successful_outfits = []
                failed_count = 0
                
                for i, result in enumerate(outfits):
                    if isinstance(result, Exception):
                        logger_service.error(f"Failed to generate outfit #{i + 1}: {str(result)}")
                        failed_count += 1
                    else:
                        successful_outfits.append(result)

                if not successful_outfits:
                    # All outfit generations failed
                    raise Exception(f"Failed to generate any outfits. {failed_count} out of {num_items} failed.")

                if failed_count > 0:
                    logger_service.warning(f"Generated {len(successful_outfits)} outfits successfully, {failed_count} failed")

                # Create result message
                if len(successful_outfits) == 1:
                    result_message = f"Successfully generated outfit: {successful_outfits[0].name}"
                else:
                    outfit_names = [outfit.name for outfit in successful_outfits]
                    result_message = f"Successfully generated {len(successful_outfits)} outfits: {', '.join(outfit_names)}"
                
                return StylistResponse(
                    user_prompt=request.prompt,
                    intent=intent,
                    result=result_message,
                    success=True,
                    data=successful_outfits,
                )
                
            except Exception as e:
                logger_service.error(f"Error during parallel outfit generation: {str(e)}")
                raise

        elif intent == "find_products":
            logger_service.info("Routing to product search")
            products: List[Product] = await stylist_service.search_for_products(40, evaluate_results=False)

            # Save products to database in background (non-blocking)
            asyncio.create_task(_save_products_to_db(products, database_service))
            logger_service.info(f"Started background task to save {len(products)} products to database")

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

