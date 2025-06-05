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
    price: Optional[float] = None
    link: Optional[str] = None
    images: List[str] = []
    source: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    caption: Optional[str] = None
    match_score: Optional[float] = None
    match_explanation: Optional[str] = None

class Outfit(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    items: List[Product]

# Google Lens API Models
class ProductMatch(BaseModel):
    position: int
    title: str
    link: str
    source: str
    source_icon: str
    thumbnail: str
    thumbnail_width: int
    thumbnail_height: int
    image: str
    image_width: int
    image_height: int


class User(BaseModel):
    id: str
    name: Optional[str] = None
    gender: Optional[str] = None
    preferred_brands: List[str] = []