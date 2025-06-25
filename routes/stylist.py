from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import uuid
from services.stylist import StylistService, Outfit
from services.auth import AuthService
from services.db import get_database_service, DatabaseService, DatabaseOutfit, DatabaseProduct
from utils.models import User
from utils.auth import get_current_user
from services.image import ImageService

# Create router for stylist endpoints
router = APIRouter()

# Initialize auth service
auth_service = AuthService()

class CreateOutfitResponse(BaseModel):
    user_prompt: str
    outfits: List[Outfit] = []
    success: bool = True

class CreateOutfitRequest(BaseModel):
    prompt: str


def convert_outfit_to_database_models(outfit: Outfit):
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

@router.post("/stylist/create-outfit", response_model=CreateOutfitResponse)
async def create_outfit(
    request: CreateOutfitRequest, 
    user: User = Depends(get_current_user),
    db_service: DatabaseService = Depends(get_database_service)
):
    try:
        print("Received request to create outfit with prompt:", request.prompt)

        # User is already retrieved through dependency injection
        print("User retrieved:", user)

        # Create stylist service context from user data
        service = StylistService(user=user, user_prompt=request.prompt)
        outfit: Outfit = await service.run()
        
        print(f"\n✅ Generated outfit concept: {outfit.name}")

        print(f"📝 Generating outfit image: {outfit.name}...")
        image_service = ImageService()
        outfit_image = image_service.generate_image(outfit)
        outfit.image_url = outfit_image 
        print(f"✅ Generated outfit image: {outfit_image}")

        # Convert outfit concept to database models
        db_outfit, db_products = convert_outfit_to_database_models(outfit)
        print(f"📝 Saving outfit with {len(db_products)} products to database...")

        # Save to database
        save_result = db_service.insert_outfit_with_products(db_outfit, db_products)

        if save_result["success"]:
            print(f"✅ Outfit saved successfully with ID: {save_result['outfit_id']}")
            return CreateOutfitResponse(
                user_prompt=request.prompt,
                outfits=[outfit],
                success=True
            )
        else:
            # Log the database error but still return the outfit concept
            print(f"⚠️ Failed to save outfit to database: {save_result['message']}")
            print("Returning outfit concept without database persistence")
            return CreateOutfitResponse(
                user_prompt=request.prompt,
                outfits=[outfit],
                success=True
            )

    except HTTPException:
        raise
    except Exception as e:
        print("Error creating outfit:", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create outfit: {str(e)}"
        )
