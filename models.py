from pydantic import BaseModel
from typing import List, Optional

class SellerInfo(BaseModel):
    seller_name: Optional[str] = None
    direct_link: Optional[str] = None
    base_price: Optional[str] = None
    shipping: Optional[str] = None
    total_price: Optional[str] = None
    delivery_info: List[str] = []

class ProductInfo(BaseModel):
    product_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    conditions: List[str] = []
    prices: List[str] = []
    images: List[str] = []
    extensions: List[str] = []
    sizes: List[str] = []

class ProductResponse(BaseModel):
    product: ProductInfo
    seller: SellerInfo

class Product(BaseModel):
    id: str
    query: Optional[str] = None
    title: Optional[str] = None
    price: Optional[str] = None
    link: Optional[str] = None
    images: List[str] = []
    source: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None

class Outfit(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    items: List[Product]

class StylistServiceResult(BaseModel):
    user_prompt: str
    outfits: List[Outfit]