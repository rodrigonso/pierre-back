from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from utils.auth import get_current_user
from utils.models import User, RecommendationRequest, OutfitRecommendationResponse, SingleOutfitRecommendation, RecommendationMatchFactors
from services.recommendation import get_recommendation_service, RecommendationService, OutfitRecommendation
from services.db import get_database_service, DatabaseService
from services.logger import get_logger_service

logger_service = get_logger_service()

# Create router for recommendation endpoints
router = APIRouter(prefix="/api", tags=["recommendations"])

# ============================================================================
# RECOMMENDATION ENDPOINTS
# ============================================================================

@router.post("/recommendations/outfits", response_model=OutfitRecommendationResponse)
async def get_outfit_recommendations(
    request: RecommendationRequest,
    current_user: User = Depends(get_current_user),
    recommendation_service: RecommendationService = Depends(get_recommendation_service),
    database_service: DatabaseService = Depends(get_database_service)
) -> OutfitRecommendationResponse:
    """
    Get personalized outfit recommendations for the current user.
    
    This endpoint analyzes the user's preferences, interaction history, and collections
    to provide personalized outfit recommendations. The recommendation algorithm considers:
    
    - User's stated preferences (brands, styles, colors)
    - Interaction history (liked/disliked outfits and products)
    - Items in user's collections
    - Outfit popularity and quality metrics
    
    Args:
        request: Recommendation request parameters
        current_user: Authenticated user
        recommendation_service: Recommendation service dependency
        database_service: Database service dependency
        
    Returns:
        OutfitRecommendationResponse: Personalized outfit recommendations with scores and reasoning
        
    Raises:
        HTTPException: If recommendation generation fails
    """
    try:
        logger_service.info(
            f"Generating outfit recommendations for user {current_user.id} "
            f"(limit: {request.limit}, exclude_liked: {request.exclude_liked})"
        )
        
        # Generate recommendations using the recommendation service
        recommendations_response = await recommendation_service.get_personalized_recommendations(
            user=current_user,
            database_service=database_service,
            limit=request.limit,
            exclude_liked=request.exclude_liked,
            style_filter=request.style_filter
        )
        
        # Convert internal recommendation format to API response format
        api_recommendations = []
        for rec in recommendations_response.recommendations:
            # Include match factors breakdown if requested
            match_factors = None
            if request.include_reasoning and rec.match_factors:
                match_factors = RecommendationMatchFactors(
                    user_preferences=rec.match_factors.get('user_preferences', 0.0),
                    interaction_history=rec.match_factors.get('interaction_history', 0.0),
                    collection_similarity=rec.match_factors.get('collection_similarity', 0.0),
                    product_compatibility=rec.match_factors.get('product_compatibility', 0.0),
                    outfit_popularity=rec.match_factors.get('outfit_popularity', 0.0)
                )
            
            api_rec = SingleOutfitRecommendation(
                outfit=rec.outfit,
                score=rec.score,
                reasoning=rec.reasoning if request.include_reasoning else [],
                match_factors=match_factors
            )
            api_recommendations.append(api_rec)
        
        # Determine success message based on results
        message = None
        if not api_recommendations:
            if recommendations_response.user_profile_strength < 0.3:
                message = "No recommendations available. Try liking some outfits or products to improve recommendations."
            else:
                message = "No new recommendations available. Try adjusting your preferences or check back later."
        elif recommendations_response.user_profile_strength < 0.5:
            message = f"Found {len(api_recommendations)} recommendations. Like more outfits and products to get better personalized suggestions!"
        else:
            message = f"Found {len(api_recommendations)} personalized recommendations based on your preferences and activity."
        
        response = OutfitRecommendationResponse(
            recommendations=api_recommendations,
            total_count=recommendations_response.total_count,
            user_profile_strength=recommendations_response.user_profile_strength,
            algorithm_version=recommendations_response.algorithm_version,
            success=True,
            message=message
        )
        
        logger_service.success(
            f"Generated {len(api_recommendations)} recommendations for user {current_user.id} "
            f"(profile strength: {recommendations_response.user_profile_strength:.2f})"
        )
        
        return response
        
    except Exception as e:
        error_msg = f"Failed to generate outfit recommendations: {str(e)}"
        logger_service.error(error_msg)
        raise HTTPException(
            status_code=500,
            detail=error_msg
        )

@router.get("/recommendations/outfits", response_model=OutfitRecommendationResponse)
async def get_outfit_recommendations_get(
    limit: int = Query(20, ge=1, le=50, description="Maximum number of recommendations"),
    exclude_liked: bool = Query(True, description="Exclude already liked outfits"),
    style_filter: Optional[str] = Query(None, description="Filter by specific styles"),
    include_reasoning: bool = Query(True, description="Include reasoning for recommendations"),
    current_user: User = Depends(get_current_user),
    recommendation_service: RecommendationService = Depends(get_recommendation_service),
    database_service: DatabaseService = Depends(get_database_service)
) -> OutfitRecommendationResponse:
    """
    Get personalized outfit recommendations for the current user (GET version).
    
    This is a GET endpoint version of the recommendation API for easier testing
    and integration with simple HTTP clients.
    
    Args:
        limit: Maximum number of recommendations to return (1-50)
        exclude_liked: Whether to exclude already liked outfits
        style_filter: Filter by specific styles (comma-separated)
        include_reasoning: Whether to include reasoning for recommendations
        current_user: Authenticated user
        recommendation_service: Recommendation service dependency
        database_service: Database service dependency
        
    Returns:
        OutfitRecommendationResponse: Personalized outfit recommendations
        
    Raises:
        HTTPException: If recommendation generation fails
    """
    # Create request object and delegate to POST endpoint logic
    request = RecommendationRequest(
        limit=limit,
        exclude_liked=exclude_liked,
        style_filter=style_filter,
        include_reasoning=include_reasoning
    )
    
    return await get_outfit_recommendations(
        request=request,
        current_user=current_user,
        recommendation_service=recommendation_service,
        database_service=database_service
    )

@router.get("/recommendations/profile-strength", response_model=dict)
async def get_user_profile_strength(
    current_user: User = Depends(get_current_user),
    recommendation_service: RecommendationService = Depends(get_recommendation_service),
    database_service: DatabaseService = Depends(get_database_service)
) -> dict:
    """
    Get the user's profile strength for recommendations.
    
    This endpoint returns information about how much data is available for
    generating personalized recommendations, along with suggestions for
    improving recommendation quality.
    
    Args:
        current_user: Authenticated user
        recommendation_service: Recommendation service dependency
        database_service: Database service dependency
        
    Returns:
        Dict containing profile strength and improvement suggestions
        
    Raises:
        HTTPException: If profile analysis fails
    """
    try:
        logger_service.info(f"Analyzing profile strength for user {current_user.id}")
        
        # Gather user profile data (same as recommendation service)
        user_profile_data = await recommendation_service._gather_user_profile_data(
            current_user, database_service
        )
        
        # Calculate profile strength
        profile_strength = recommendation_service._calculate_profile_strength(user_profile_data)
        
        # Generate improvement suggestions
        suggestions = []
        preferences = user_profile_data.get('preferences', {})
        
        if not preferences.get('positive_styles'):
            suggestions.append("Add your preferred styles to your profile")
        if not preferences.get('positive_brands'):
            suggestions.append("Add your preferred brands to your profile")
        if not preferences.get('positive_colors'):
            suggestions.append("Add your preferred colors to your profile")
        
        liked_outfits_count = len(user_profile_data.get('liked_outfits', []))
        liked_products_count = len(user_profile_data.get('liked_products', []))
        
        if liked_outfits_count < 5:
            suggestions.append(f"Like more outfits ({liked_outfits_count}/10+ recommended)")
        if liked_products_count < 10:
            suggestions.append(f"Like more products ({liked_products_count}/20+ recommended)")
            
        collections_count = len(user_profile_data.get('collection_items', []))
        if collections_count < 5:
            suggestions.append("Create collections to organize your favorite items")
        
        # Determine profile level
        if profile_strength >= 0.8:
            level = "Excellent"
            description = "You have a very strong profile for personalized recommendations!"
        elif profile_strength >= 0.6:
            level = "Good"
            description = "You have a good profile for recommendations with room for improvement."
        elif profile_strength >= 0.4:
            level = "Fair"
            description = "Your profile needs more data for better personalized recommendations."
        else:
            level = "Needs Improvement"
            description = "Add more preferences and interactions to get personalized recommendations."
        
        response = {
            "profile_strength": profile_strength,
            "level": level,
            "description": description,
            "data_summary": {
                "liked_outfits": liked_outfits_count,
                "liked_products": liked_products_count,
                "collections": collections_count,
                "style_preferences": len(preferences.get('positive_styles', [])),
                "brand_preferences": len(preferences.get('positive_brands', [])),
                "color_preferences": len(preferences.get('positive_colors', []))
            },
            "improvement_suggestions": suggestions,
            "success": True
        }
        
        logger_service.success(
            f"Profile strength analysis complete for user {current_user.id}: {profile_strength:.2f}"
        )
        
        return response
        
    except Exception as e:
        error_msg = f"Failed to analyze profile strength: {str(e)}"
        logger_service.error(error_msg)
        raise HTTPException(
            status_code=500,
            detail=error_msg
        )
