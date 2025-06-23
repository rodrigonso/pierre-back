from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from typing import List
from pydantic import BaseModel
from services.stylist import StylistService, OutfitConcept, StylistServiceContext
from services.auth import AuthService
from utils.models import User

# Create router for stylist endpoints
router = APIRouter()

# Initialize auth service
auth_service = AuthService()

class CreateOutfitResponse(BaseModel):
    user_prompt: str
    outfits: List[OutfitConcept] = []
    success: bool = True

class CreateOutfitRequest(BaseModel):
    user_id: str
    prompt: str

@router.post("/stylist/create-outfit", response_model=CreateOutfitResponse)
async def create_stylist(request: CreateOutfitRequest):

    try:
        print("Received request to create outfit with prompt:", request.prompt)

        # Get user information using dependency injection
        user = auth_service.get_user_by_id(request.user_id)
        print("User retrieved:", user)
        
        # Create stylist service context from user data
        context = StylistServiceContext(
            gender=user.gender or "unspecified",
            positive_styles=user.positive_styles,
            negative_styles=user.negative_styles,
            positive_brands=user.positive_brands,
            negative_brands=user.negative_brands,
            positive_colors=user.positive_colors,
            negative_colors=user.negative_colors,
            user_prompt=request.prompt
        )

        service = StylistService(user=context, user_prompt=request.prompt)
        res: OutfitConcept = await service.run()

        return CreateOutfitResponse(
            user_prompt=request.prompt,
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