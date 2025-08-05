from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

from services.db import DatabaseOutfit, DatabaseProduct

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

    positive_brands: List[str] = []
    negative_brands: List[str] = []

    positive_styles: List[str] = []
    negative_styles: List[str] = []

    positive_colors: List[str] = []
    negative_colors: List[str] = []
    
    invite_code_used: Optional[str] = None
    
    # Subscription and usage fields
    subscription_status: str = "free"
    free_requests_used: int = 0
    free_requests_limit: int = 4
    
    def can_make_pierre_request(self) -> bool:
        """Check if user can make a Pierre request based on subscription status"""
        if self.subscription_status in ['premium', 'pro']:
            return True
        return self.free_requests_used < self.free_requests_limit
    
    def get_remaining_free_requests(self) -> int:
        """Get number of remaining free requests"""
        if self.subscription_status in ['premium', 'pro']:
            return -1  # Unlimited
        return max(0, self.free_requests_limit - self.free_requests_used)

class UserProfile(BaseModel):
    user_id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    provider: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    user_metadata: Optional[dict] = None
    app_metadata: Optional[dict] = None

# Collection Models
class CollectionCreate(BaseModel):
    """
    Model for creating a new collection
    
    Attributes:
        name: Name of the collection (1-100 characters)
        description: Optional description for the collection
    """
    name: str = Field(..., min_length=1, max_length=100, description="Collection name")
    description: Optional[str] = Field(None, max_length=500, description="Optional description")
    image_url: Optional[str] = Field(None, description="Optional image URL")

class CollectionUpdate(BaseModel):
    """
    Model for updating an existing collection
    
    Attributes:
        name: Updated name of the collection
        description: Updated description for the collection
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Collection name")
    description: Optional[str] = Field(None, max_length=500, description="Optional description")
    image_b64: Optional[str] = None

class CollectionItem(BaseModel):
    """
    Model for an item within a collection
    
    Attributes:
        id: Unique identifier for the collection item
        item_type: Type of item ('product' or 'outfit')
        item_id: ID of the product or outfit
        added_at: When the item was added to the collection
    """
    id: str
    item_type: str = Field(..., pattern="^(product|outfit)$", description="Item type: product or outfit")
    item_id: str
    added_at: datetime

class CollectionItemWithData(BaseModel):
    """
    Model for a collection item with actual product/outfit data included
    
    Attributes:
        id: Unique identifier for the collection item
        item_type: Type of item ('product' or 'outfit')
        item_id: ID of the product or outfit
        added_at: When the item was added to the collection
        data: The actual product or outfit data
    """
    id: str
    item_type: str = Field(..., pattern="^(product|outfit)$", description="Item type: product or outfit")
    item_id: str
    added_at: datetime
    data: Optional[DatabaseProduct | DatabaseOutfit] = None  # Will contain product or outfit data

class Collection(BaseModel):
    """
    Model for a complete collection with metadata
    
    Attributes:
        id: Unique identifier for the collection
        user_id: ID of the user who owns the collection
        name: Name of the collection
        description: Optional description
        created_at: When the collection was created
        updated_at: When the collection was last updated
        item_count: Number of items in the collection
    """
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    item_count: int = 0

class CollectionWithItems(BaseModel):
    """
    Model for a collection with its items included
    
    Attributes:
        id: Unique identifier for the collection
        user_id: ID of the user who owns the collection
        name: Name of the collection
        description: Optional description
        created_at: When the collection was created
        updated_at: When the collection was last updated
        items: List of items in the collection with actual data
    """
    id: str | int
    user_id: str
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[CollectionItemWithData] = []

class AddItemToCollection(BaseModel):
    """
    Model for adding an item to a collection
    
    Attributes:
        item_type: Type of item to add ('product' or 'outfit')
        item_id: ID of the product or outfit to add
    """
    item_type: str = Field(..., pattern="^(product|outfit)$", description="Item type: product or outfit")
    item_id: str | int = Field(..., description="ID of the item to add")

# Recommendation Models
class RecommendationRequest(BaseModel):
    """
    Model for outfit recommendation requests
    
    Attributes:
        limit: Maximum number of recommendations to return (1-50)
        exclude_liked: Whether to exclude already liked outfits
        style_filter: Optional style filter to apply
        include_reasoning: Whether to include reasoning for recommendations
    """
    limit: int = Field(20, ge=1, le=50, description="Maximum number of recommendations")
    exclude_liked: bool = Field(True, description="Exclude already liked outfits")
    style_filter: Optional[str] = Field(None, description="Filter by specific styles (comma-separated)")
    include_reasoning: bool = Field(True, description="Include reasoning for recommendations")

class RecommendationMatchFactors(BaseModel):
    """
    Model for recommendation match factors breakdown
    
    Attributes:
        user_preferences: Score based on user's stated preferences
        interaction_history: Score based on user's interaction history
        collection_similarity: Score based on user's collections
        product_compatibility: Score based on similarity to liked individual products
        outfit_popularity: Score based on outfit's popularity
    """
    user_preferences: float = Field(..., description="User preferences alignment score")
    interaction_history: float = Field(..., description="Interaction history similarity score")
    collection_similarity: float = Field(..., description="Collection similarity score")
    product_compatibility: float = Field(..., description="Individual product similarity score")
    outfit_popularity: float = Field(..., description="Outfit popularity score")

class SingleOutfitRecommendation(BaseModel):
    """
    Model for a single outfit recommendation
    
    Attributes:
        outfit: The recommended outfit with all details
        score: Overall recommendation score (0.0-1.0)
        reasoning: List of reasons why this outfit was recommended
        match_factors: Breakdown of scoring factors
    """
    outfit: DatabaseOutfit
    score: float = Field(..., ge=0.0, le=1.0, description="Recommendation score")
    reasoning: List[str] = Field(..., description="Reasons for recommendation")
    match_factors: Optional[RecommendationMatchFactors] = Field(None, description="Score breakdown")

class OutfitRecommendationResponse(BaseModel):
    """
    Model for outfit recommendation API response
    
    Attributes:
        recommendations: List of recommended outfits with scores
        total_count: Total number of potential recommendations
        user_profile_strength: How much we know about the user (0.0-1.0)
        algorithm_version: Version of the recommendation algorithm used
        success: Whether the recommendation generation was successful
        message: Optional message about the recommendations
    """
    recommendations: List[SingleOutfitRecommendation]
    total_count: int = Field(..., description="Total recommendations before limiting")
    user_profile_strength: float = Field(..., ge=0.0, le=1.0, description="User profile completeness")
    algorithm_version: str = Field("v1.0", description="Recommendation algorithm version")
    success: bool = Field(True, description="Whether recommendation was successful")
    message: Optional[str] = Field(None, description="Optional message about recommendations")