from fastapi import APIRouter, HTTPException, status
from datetime import datetime
from typing import List
from pydantic import BaseModel
from services.stylist import StylistService, OutfitConcept, StylistServiceContext
from utils.models import User

# Create router for stylist endpoints
router = APIRouter()

# In-memory storage for demo purposes (replace with database in production)
stylists_db: List[dict] = []


class CreateOutfitResponse(BaseModel):
    user_prompt: str
    outfits: List[OutfitConcept] = []
    success: bool = True

class CreateOutfitRequest(BaseModel):
    user_prompt: str
    gender: str
    positive_styles: List[str] = []
    negative_styles: List[str] = []

    positive_brands: List[str] = []
    negative_brands: List[str] = []
    
    positive_colors: List[str] = []
    negative_colors: List[str] = []

@router.post("/stylist/create-outfit", response_model=CreateOutfitResponse)
async def create_stylist(request: CreateOutfitRequest):

    try:
        print("Received request to create outfit with prompt:", request.user_prompt)

        # TODO: grab the user info from the request context or session
        user = StylistServiceContext(**request.model_dump())

        service = StylistService(user=user, user_prompt=request.user_prompt)
        res: OutfitConcept = await service.run()
        print("Stylist service response:", res)

        return CreateOutfitResponse(
            user_prompt=request.user_prompt,
            outfits=[res],
            success=True
        )

    except HTTPException:
        raise
    except Exception as e:
        print("Error creating stylist:", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create stylist: {str(e)}"
        )