from fastapi import APIRouter, Depends
from datetime import datetime
import uuid
from typing import List
from pydantic import BaseModel
from utils.models import User
from utils.auth import get_current_user

# Create router for product endpoints
router = APIRouter()

class ProductsResponse(BaseModel):
    query: str
    products: List[dict]
    success: bool = True

@router.get("/products/", response_model=ProductsResponse)
async def get_all_products(request, current_user: User = Depends(get_current_user)):

    return "test"

