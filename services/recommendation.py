from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import numpy as np
from openai import OpenAI
import os
from services.db import DatabaseService, DatabaseOutfit, DatabaseProduct, DatabasePaginatedResponse
from services.logger import get_logger_service
from utils.models import User
from pydantic import BaseModel
import asyncio
from collections import defaultdict, Counter
import time
from functools import lru_cache

logger_service = get_logger_service()

# OPTIMIZATION: In-memory cache for user profile data
_profile_cache = {}
_profile_cache_ttl = {}
PROFILE_CACHE_DURATION = 300  # 5 minutes

class RecommendationWeights(BaseModel):
    """
    Configuration for recommendation algorithm weights
    """
    user_preferences: float = 0.25     # Style, brand, color preferences  
    interaction_history: float = 0.35  # Likes/dislikes on outfits and products
    collection_similarity: float = 0.15 # Items in user's collections
    outfit_popularity: float = 0.1     # Global popularity metrics
    # product_compatibility gets 0.15 weight (added in scoring method)

class OutfitRecommendation(BaseModel):
    """
    Single outfit recommendation with score and reasoning
    """
    outfit: DatabaseOutfit
    score: float
    reasoning: List[str]
    match_factors: Dict[str, float]

class RecommendationResponse(BaseModel):
    """
    Complete recommendation response
    """
    recommendations: List[OutfitRecommendation]
    total_count: int
    user_profile_strength: float  # How much data we have about the user (0-1)
    algorithm_version: str = "v1.0"

class RecommendationService:
    """
    Advanced recommendation service that analyzes user preferences, interactions,
    and collections to recommend personalized outfits.
    
    The service uses multiple signals:
    - User profile preferences (brands, styles, colors)
    - Interaction history (liked/disliked outfits and products)
    - Collections analysis (what user saves/organizes)
    - Semantic similarity using embeddings
    - Popularity and trending metrics
    """
    
    def __init__(self):
        """Initialize the recommendation service with OpenAI client."""
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.weights = RecommendationWeights()
    
    async def get_personalized_recommendations(
        self,
        user: User,
        database_service: DatabaseService,
        limit: int = 20,
        exclude_liked: bool = True,
        style_filter: Optional[str] = None
    ) -> RecommendationResponse:
        """
        Get personalized outfit recommendations for a user.
        OPTIMIZED: Uses caching and parallel processing for better performance.
        
        Args:
            user: User object with preferences and ID
            database_service: Database service for data access
            limit: Maximum number of recommendations to return
            exclude_liked: Whether to exclude already liked outfits
            style_filter: Optional style filter to apply
            
        Returns:
            RecommendationResponse with scored recommendations
        """
        try:
            logger_service.info(f"Generating recommendations for user {user.id}")
            
            # Step 1: Gather user data for profiling (with caching)
            user_profile_data = await self._get_cached_user_profile_data(user, database_service)
            
            # Step 2: Get candidate outfits (exclude already liked if requested)
            candidates = await self._get_candidate_outfits(
                user.id, database_service, exclude_liked, style_filter, user
            )
            
            if not candidates:
                logger_service.warning(f"No candidate outfits found for user {user.id}")
                return RecommendationResponse(
                    recommendations=[],
                    total_count=0,
                    user_profile_strength=0.0
                )
            
            # Step 3: OPTIMIZATION - Score outfits in parallel batches for better performance
            scored_recommendations = await self._score_outfits_parallel(
                candidates, user, user_profile_data, database_service
            )
            
            # Step 4: Sort by score and limit results
            scored_recommendations.sort(key=lambda x: x.score, reverse=True)
            top_recommendations = scored_recommendations[:limit]
            
            # Step 5: Calculate user profile strength
            profile_strength = self._calculate_profile_strength(user_profile_data)
            
            logger_service.success(
                f"Generated {len(top_recommendations)} recommendations for user {user.id} "
                f"(profile strength: {profile_strength:.2f})"
            )
            
            return RecommendationResponse(
                recommendations=top_recommendations,
                total_count=len(scored_recommendations),
                user_profile_strength=profile_strength
            )
            
        except Exception as e:
            logger_service.error(f"Failed to generate recommendations: {str(e)}")
            return RecommendationResponse(
                recommendations=[],
                total_count=0,
                user_profile_strength=0.0
            )
    
    async def _get_cached_user_profile_data(
        self, 
        user: User, 
        database_service: DatabaseService
    ) -> Dict[str, Any]:
        """
        Get user profile data with caching to avoid redundant database queries.
        OPTIMIZATION: Caches user profile data for 5 minutes to speed up recommendations.
        """
        global _profile_cache, _profile_cache_ttl
        
        cache_key = f"profile_{user.id}"
        current_time = time.time()
        
        # Check if we have valid cached data
        if (cache_key in _profile_cache and 
            cache_key in _profile_cache_ttl and 
            current_time - _profile_cache_ttl[cache_key] < PROFILE_CACHE_DURATION):
            
            logger_service.info(f"Using cached profile data for user {user.id}")
            return _profile_cache[cache_key]
        
        # Cache miss or expired - fetch fresh data
        logger_service.info(f"Fetching fresh profile data for user {user.id}")
        profile_data = await self._gather_user_profile_data(user, database_service)
        
        # Cache the result
        _profile_cache[cache_key] = profile_data
        _profile_cache_ttl[cache_key] = current_time
        
        # Clean up old cache entries (simple cleanup)
        self._cleanup_profile_cache()
        
        return profile_data
    
    def _cleanup_profile_cache(self):
        """Clean up expired cache entries to prevent memory bloat."""
        global _profile_cache, _profile_cache_ttl
        
        current_time = time.time()
        expired_keys = [
            key for key, timestamp in _profile_cache_ttl.items()
            if current_time - timestamp >= PROFILE_CACHE_DURATION
        ]
        
        for key in expired_keys:
            _profile_cache.pop(key, None)
            _profile_cache_ttl.pop(key, None)
    
    async def _score_outfits_parallel(
        self,
        candidates: List[DatabaseOutfit],
        user: User,
        user_profile_data: Dict[str, Any],
        database_service: DatabaseService,
        batch_size: int = 8  # OPTIMIZATION: Reduced batch size to prevent DB overload
    ) -> List[OutfitRecommendation]:
        """
        Score outfits in parallel batches for better performance.
        OPTIMIZED: Processes multiple outfits concurrently with controlled batch size.
        """
        scored_recommendations = []
        
        # OPTIMIZATION: Add early termination if we have enough high-scoring results
        high_score_threshold = 0.7
        target_high_scores = min(50, len(candidates))  # Cap at 50 high-scoring outfits
        
        # Process outfits in smaller batches to avoid overwhelming the system
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i + batch_size]
            
            # Create async tasks for parallel processing
            tasks = [
                self._score_outfit_for_user(outfit, user, user_profile_data, database_service)
                for outfit in batch
            ]
            
            try:
                # Wait for all tasks in the batch to complete with timeout
                batch_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=30.0  # 30 second timeout per batch
                )
                
                # Process results and handle any exceptions
                for outfit, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        logger_service.error(f"Error scoring outfit {outfit.id}: {str(result)}")
                        continue
                    
                    score, reasoning, match_factors = result
                    if score > 0:  # Only include positive scores
                        recommendation = OutfitRecommendation(
                            outfit=outfit,
                            score=score,
                            reasoning=reasoning,
                            match_factors=match_factors
                        )
                        scored_recommendations.append(recommendation)
                
                # OPTIMIZATION: Early termination if we have enough high-quality results
                high_scoring = [r for r in scored_recommendations if r.score >= high_score_threshold]
                if len(high_scoring) >= target_high_scores:
                    logger_service.info(
                        f"Early termination: Found {len(high_scoring)} high-scoring outfits"
                    )
                    break
                    
            except asyncio.TimeoutError:
                logger_service.warning(f"Batch scoring timeout for batch starting at {i}")
                continue
            except Exception as e:
                logger_service.error(f"Error processing batch starting at {i}: {str(e)}")
                continue
        
        return scored_recommendations
    
    async def _gather_user_profile_data(
        self, 
        user: User, 
        database_service: DatabaseService
    ) -> Dict[str, Any]:
        """
        Gather comprehensive user profile data for recommendation scoring.
        OPTIMIZED: Uses parallel fetching to reduce total time.
        
        Returns:
            Dict containing user interaction patterns and preferences
        """
        profile_data = {
            'preferences': {
                'positive_brands': user.positive_brands,
                'negative_brands': user.negative_brands,
                'positive_styles': user.positive_styles,
                'negative_styles': user.negative_styles,
                'positive_colors': user.positive_colors,
                'negative_colors': user.negative_colors
            },
            'liked_outfits': [],
            'disliked_outfits': [],
            'liked_products': [],
            'collection_items': [],
            'interaction_patterns': {}
        }
        
        try:
            # OPTIMIZATION: Fetch all user data in parallel instead of sequentially
            tasks = [
                database_service.get_liked_outfits_with_products(user.id, page=1, page_size=100),
                database_service.get_liked_products(user.id, page=1, page_size=100),
                self._get_user_collection_items(user.id, database_service)
            ]
            
            # Wait for all data fetching to complete in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and handle any exceptions
            if not isinstance(results[0], Exception):
                profile_data['liked_outfits'] = results[0].data
            else:
                logger_service.error(f"Error fetching liked outfits: {str(results[0])}")
            
            if not isinstance(results[1], Exception):
                profile_data['liked_products'] = results[1].data
            else:
                logger_service.error(f"Error fetching liked products: {str(results[1])}")
            
            if not isinstance(results[2], Exception):
                profile_data['collection_items'] = results[2]
            else:
                logger_service.error(f"Error fetching collection items: {str(results[2])}")
            
            # Analyze interaction patterns
            profile_data['interaction_patterns'] = self._analyze_interaction_patterns(
                profile_data['liked_outfits'],
                profile_data['liked_products']
            )
            
        except Exception as e:
            logger_service.error(f"Error gathering user profile data: {str(e)}")
        
        return profile_data
    
    async def _get_user_collection_items(
        self,
        user_id: str,
        database_service: DatabaseService
    ) -> List[Dict[str, Any]]:
        """Get items from user's collections for additional preference signals."""
        collection_items = []
        
        try:
            # This would require adding a method to database service to get collection items
            # For now, we'll return empty list and implement this when collections service is enhanced
            pass
        except Exception as e:
            logger_service.error(f"Error getting collection items: {str(e)}")
        
        return collection_items
    
    def _analyze_interaction_patterns(
        self,
        liked_outfits: List[DatabaseOutfit],
        liked_products: List[DatabaseProduct]
    ) -> Dict[str, Any]:
        """
        Analyze user interaction patterns to extract preferences.
        
        Returns:
            Dict with analyzed patterns like preferred styles, brands, colors, etc.
        """
        patterns = {
            'preferred_outfit_styles': Counter(),
            'preferred_product_brands': Counter(),
            'preferred_product_types': Counter(),
            'preferred_colors': Counter(),
            'preferred_product_colors': Counter(),
            'price_range_preference': {'min': None, 'max': None, 'avg': None},
            'recency_bias': None  # How much user prefers recent vs older items
        }
        
        try:
            # Analyze outfit style preferences
            for outfit in liked_outfits:
                if outfit.style:
                    # Handle comma-separated styles
                    styles = [s.strip().lower() for s in outfit.style.split(',')]
                    for style in styles:
                        patterns['preferred_outfit_styles'][style] += 1
            
            # Analyze product brand preferences
            for product in liked_products:
                if product.brand:
                    patterns['preferred_product_brands'][product.brand.lower()] += 1
                
                # Analyze product type preferences
                if product.type:
                    patterns['preferred_product_types'][product.type.lower()] += 1
                
                # Analyze color preferences from product titles/descriptions
                if product.title:
                    colors = self._extract_colors_from_text(product.title.lower())
                    for color in colors:
                        patterns['preferred_colors'][color] += 1
                        patterns['preferred_product_colors'][color] += 1
                
                # Also analyze colors from product descriptions
                if product.description:
                    colors = self._extract_colors_from_text(product.description.lower())
                    for color in colors:
                        patterns['preferred_product_colors'][color] += 1
            
            # Analyze price preferences
            prices = []
            for product in liked_products:
                if product.price and product.price > 0:
                    prices.append(product.price)
            
            if prices:
                patterns['price_range_preference'] = {
                    'min': min(prices),
                    'max': max(prices),
                    'avg': sum(prices) / len(prices)
                }
            
        except Exception as e:
            logger_service.error(f"Error analyzing interaction patterns: {str(e)}")
        
        return patterns
    
    def _extract_colors_from_text(self, text: str) -> List[str]:
        """Extract color names from text."""
        # Common fashion colors
        colors = [
            'black', 'white', 'gray', 'grey', 'navy', 'blue', 'red', 'pink',
            'green', 'yellow', 'orange', 'purple', 'brown', 'beige', 'tan',
            'cream', 'gold', 'silver', 'maroon', 'olive', 'teal', 'coral',
            'lavender', 'mint', 'burgundy', 'khaki', 'denim'
        ]
        
        found_colors = []
        for color in colors:
            if color in text:
                found_colors.append(color)
        
        return found_colors
    
    async def _get_candidate_outfits(
        self,
        user_id: str,
        database_service: DatabaseService,
        exclude_liked: bool = True,
        style_filter: Optional[str] = None,
        user: Optional[User] = None  # FIXED: Accept user object directly
    ) -> List[DatabaseOutfit]:
        """
        Get candidate outfits for recommendation scoring.
        OPTIMIZED: Uses smart database-level filtering to reduce candidate pool.
        
        Args:
            user_id: User ID for filtering liked outfits
            database_service: Database service
            exclude_liked: Whether to exclude already liked outfits
            style_filter: Optional style filter
            user: User object with preferences (FIXED: no need to fetch from DB)
            
        Returns:
            List of candidate outfits with products included
        """
        try:
            # OPTIMIZATION: Build style filter combining user preferences and request filter
            combined_style_filter = style_filter
            if user and user.positive_styles:
                user_styles = ','.join(user.positive_styles)
                if style_filter:
                    combined_style_filter = f"{style_filter},{user_styles}"
                else:
                    combined_style_filter = user_styles
            
            # OPTIMIZATION: Get more outfits initially but use better filtering
            outfits_response = await database_service.get_outfits_with_products(
                page=1, 
                page_size=150,  # Reduced from 200 due to better filtering
                user_id=user_id,
                include_likes=True,
                style=combined_style_filter  # Use combined style filtering
            )
            
            candidates = outfits_response.data
            
            # Filter out liked outfits if requested
            if exclude_liked:
                candidates = [outfit for outfit in candidates if not outfit.is_liked]
            
            # OPTIMIZATION: Additional filtering based on user preferences
            if user:
                candidates = self._apply_preference_filtering(candidates, user)
            
            logger_service.info(f"Found {len(candidates)} candidate outfits for recommendations after filtering")
            return candidates
            
        except Exception as e:
            logger_service.error(f"Error getting candidate outfits: {str(e)}")
            return []
    
    def _apply_preference_filtering(
        self,
        candidates: List[DatabaseOutfit],
        user_data: User
    ) -> List[DatabaseOutfit]:
        """
        Apply additional filtering based on user preferences to reduce candidates.
        OPTIMIZATION: Pre-filter candidates to reduce computational load.
        """
        filtered_candidates = []
        
        for outfit in candidates:
            # Skip outfits with negative style preferences
            if outfit.style and user_data.negative_styles:
                outfit_styles = [s.strip().lower() for s in outfit.style.split(',')]
                user_negative_styles = [s.lower() for s in user_data.negative_styles]
                if any(style in user_negative_styles for style in outfit_styles):
                    continue  # Skip this outfit
            
            # Skip outfits with too many negative brand preferences
            if outfit.products and user_data.negative_brands:
                outfit_brands = [p.brand.lower() for p in outfit.products if p.brand]
                user_negative_brands = [b.lower() for b in user_data.negative_brands]
                negative_brand_count = sum(1 for brand in outfit_brands if brand in user_negative_brands)
                
                # Skip if more than half the products are from negative brands
                if outfit_brands and negative_brand_count > len(outfit_brands) / 2:
                    continue
            
            filtered_candidates.append(outfit)
        
        return filtered_candidates
    
    async def _score_outfit_for_user(
        self,
        outfit: DatabaseOutfit,
        user: User,
        user_profile_data: Dict[str, Any],
        database_service: DatabaseService
    ) -> Tuple[float, List[str], Dict[str, float]]:
        """
        Score an outfit for a specific user based on multiple factors.
        OPTIMIZED: Uses tiered scoring with early termination for better performance.
        
        Returns:
            Tuple of (score, reasoning_list, match_factors_dict)
        """
        total_score = 0.0
        reasoning = []
        match_factors = {}
        
        try:
            # OPTIMIZATION: Tier 1 - Quick preference check (early termination)
            # Check for deal-breaker negative preferences first
            quick_score = self._quick_preference_check(outfit, user)
            if quick_score < 0.1:  # Early termination for very low scores
                return 0.0, ["Does not match your preferences"], {}
            
            # Factor 1: User preferences alignment
            pref_score = self._score_user_preferences_alignment(outfit, user, user_profile_data)
            match_factors['user_preferences'] = pref_score
            total_score += pref_score * self.weights.user_preferences
            
            if pref_score > 0.7:
                reasoning.append(f"Strong match with your style preferences ({pref_score:.1%})")
            elif pref_score > 0.4:
                reasoning.append(f"Good match with your preferences ({pref_score:.1%})")
            
            # OPTIMIZATION: Early termination if preferences don't match well
            if pref_score < 0.2 and len(user_profile_data.get('liked_outfits', [])) > 5:
                return total_score, reasoning, match_factors
            
            # Factor 2: Interaction history similarity
            interaction_score = self._score_interaction_history_similarity(outfit, user_profile_data)
            match_factors['interaction_history'] = interaction_score
            total_score += interaction_score * self.weights.interaction_history
            
            if interaction_score > 0.6:
                reasoning.append("Similar to outfits you've liked before")
            
            # Factor 3: Collection similarity (if user has collections)
            collection_score = self._score_collection_similarity(outfit, user_profile_data)
            match_factors['collection_similarity'] = collection_score
            total_score += collection_score * self.weights.collection_similarity
            
            if collection_score > 0.5:
                reasoning.append("Matches items in your collections")
            
            # Factor 4: Product-level compatibility based on individual product likes
            product_compat_score = self._score_product_level_compatibility(outfit, user_profile_data)
            match_factors['product_compatibility'] = product_compat_score
            total_score += product_compat_score * 0.15  # Additional weight for product-level analysis
            
            if product_compat_score > 0.7:
                reasoning.append("Contains products similar to ones you've liked")
            
            # Factor 5: Outfit popularity/quality score
            popularity_score = self._score_outfit_popularity(outfit)
            match_factors['outfit_popularity'] = popularity_score
            total_score += popularity_score * self.weights.outfit_popularity
            
            if popularity_score > 0.8:
                reasoning.append("Highly rated outfit")
            
            # Bonus factors
            if outfit.style:
                styles = [s.strip().lower() for s in outfit.style.split(',')]
                user_positive_styles = [s.lower() for s in user.positive_styles]
                if any(style in user_positive_styles for style in styles):
                    total_score += 0.1  # Bonus for exact style match
                    reasoning.append("Matches your preferred style exactly")
            
            # Penalty for negative preferences
            if outfit.style:
                styles = [s.strip().lower() for s in outfit.style.split(',')]
                user_negative_styles = [s.lower() for s in user.negative_styles]
                if any(style in user_negative_styles for style in styles):
                    total_score -= 0.2  # Penalty for negative style match
                    reasoning.append("Note: Contains a style you typically avoid")
            
            # Ensure score is between 0 and 1
            total_score = max(0.0, min(1.0, total_score))
            
        except Exception as e:
            logger_service.error(f"Error scoring outfit {outfit.id}: {str(e)}")
            total_score = 0.0
            reasoning = ["Error occurred during scoring"]
        
        return total_score, reasoning, match_factors
    
    def _quick_preference_check(self, outfit: DatabaseOutfit, user: User) -> float:
        """
        Quick check for basic preference alignment to enable early termination.
        OPTIMIZATION: Fast preliminary score to avoid detailed computation on poor matches.
        """
        score = 0.5  # Base score
        
        # Check style preferences
        if outfit.style and user.negative_styles:
            outfit_styles = [s.strip().lower() for s in outfit.style.split(',')]
            user_negative_styles = [s.lower() for s in user.negative_styles]
            if any(style in user_negative_styles for style in outfit_styles):
                return 0.0  # Deal breaker
        
        if outfit.style and user.positive_styles:
            outfit_styles = [s.strip().lower() for s in outfit.style.split(',')]
            user_positive_styles = [s.lower() for s in user.positive_styles]
            if any(style in user_positive_styles for style in outfit_styles):
                score += 0.3
        
        # Quick brand check
        if outfit.products:
            negative_brand_penalty = 0
            positive_brand_bonus = 0
            
            for product in outfit.products[:3]:  # Only check first 3 products for speed
                if product.brand:
                    brand_lower = product.brand.lower()
                    if brand_lower in [b.lower() for b in user.negative_brands]:
                        negative_brand_penalty += 0.1
                    if brand_lower in [b.lower() for b in user.positive_brands]:
                        positive_brand_bonus += 0.1
            
            score = score - negative_brand_penalty + positive_brand_bonus
        
        return max(0.0, min(1.0, score))
    
    def _score_user_preferences_alignment(
        self,
        outfit: DatabaseOutfit,
        user: User,
        user_profile_data: Dict[str, Any]
    ) -> float:
        """Score how well outfit aligns with user's stated preferences."""
        score = 0.0
        total_factors = 0
        
        try:
            # Style alignment
            if outfit.style and user.positive_styles:
                outfit_styles = [s.strip().lower() for s in outfit.style.split(',')]
                user_styles = [s.lower() for s in user.positive_styles]
                
                style_matches = sum(1 for style in outfit_styles if style in user_styles)
                if outfit_styles:
                    style_score = style_matches / len(outfit_styles)
                    score += style_score
                    total_factors += 1
            
            # Brand alignment (from products in the outfit)
            if outfit.products and user.positive_brands:
                outfit_brands = [p.brand.lower() for p in outfit.products if p.brand]
                user_brands = [b.lower() for b in user.positive_brands]
                
                brand_matches = sum(1 for brand in outfit_brands if brand in user_brands)
                if outfit_brands:
                    brand_score = brand_matches / len(outfit_brands)
                    score += brand_score
                    total_factors += 1
            
            # Color alignment (enhanced with product likes data)
            if outfit.products and user.positive_colors:
                # Extract colors from product titles/descriptions
                outfit_colors = []
                for product in outfit.products:
                    if product.title:
                        outfit_colors.extend(self._extract_colors_from_text(product.title.lower()))
                    if product.description:
                        outfit_colors.extend(self._extract_colors_from_text(product.description.lower()))
                
                user_colors = [c.lower() for c in user.positive_colors]
                color_matches = sum(1 for color in outfit_colors if color in user_colors)
                
                if outfit_colors:
                    color_score = color_matches / len(outfit_colors)
                    score += color_score
                    total_factors += 1
            
            # Product type alignment based on interaction history
            interaction_patterns = user_profile_data.get('interaction_patterns', {})
            if outfit.products and interaction_patterns.get('preferred_product_types'):
                outfit_types = [p.type.lower() for p in outfit.products if p.type]
                preferred_types = interaction_patterns['preferred_product_types']
                
                if outfit_types and preferred_types:
                    type_matches = sum(1 for ptype in outfit_types if ptype in preferred_types)
                    type_score = type_matches / len(outfit_types)
                    score += type_score * 0.8  # Weight type matching
                    total_factors += 1
            
            # Enhanced brand alignment using interaction patterns
            if outfit.products and interaction_patterns.get('preferred_product_brands'):
                outfit_brands = [p.brand.lower() for p in outfit.products if p.brand]
                preferred_brands = interaction_patterns['preferred_product_brands']
                
                if outfit_brands and preferred_brands:
                    # Weight brands by how often they were liked
                    total_brand_likes = sum(preferred_brands.values())
                    weighted_brand_score = 0
                    for brand in outfit_brands:
                        if brand in preferred_brands:
                            weight = preferred_brands[brand] / total_brand_likes
                            weighted_brand_score += weight
                    
                    if outfit_brands:
                        brand_score = weighted_brand_score / len(outfit_brands)
                        score += brand_score * 1.2  # Higher weight for proven brand preferences
                        total_factors += 1
        
        except Exception as e:
            logger_service.error(f"Error scoring user preferences: {str(e)}")
        
        return score / total_factors if total_factors > 0 else 0.0
    
    def _score_interaction_history_similarity(
        self,
        outfit: DatabaseOutfit,
        user_profile_data: Dict[str, Any]
    ) -> float:
        """Score based on similarity to user's interaction history."""
        score = 0.0
        
        try:
            interaction_patterns = user_profile_data.get('interaction_patterns', {})
            
            # Style similarity to liked outfits
            if outfit.style and interaction_patterns.get('preferred_outfit_styles'):
                outfit_styles = [s.strip().lower() for s in outfit.style.split(',')]
                preferred_styles = interaction_patterns['preferred_outfit_styles']
                
                # Calculate weighted similarity based on frequency of liked styles
                total_preferences = sum(preferred_styles.values())
                if total_preferences > 0:
                    style_similarity = 0
                    for style in outfit_styles:
                        if style in preferred_styles:
                            # Weight by how often user liked this style
                            weight = preferred_styles[style] / total_preferences
                            style_similarity += weight
                    
                    score += style_similarity / len(outfit_styles) if outfit_styles else 0
            
            # Brand similarity to liked products
            if outfit.products and interaction_patterns.get('preferred_product_brands'):
                outfit_brands = [p.brand.lower() for p in outfit.products if p.brand]
                preferred_brands = interaction_patterns['preferred_product_brands']
                
                total_brand_preferences = sum(preferred_brands.values())
                if total_brand_preferences > 0 and outfit_brands:
                    brand_similarity = 0
                    for brand in outfit_brands:
                        if brand in preferred_brands:
                            weight = preferred_brands[brand] / total_brand_preferences
                            brand_similarity += weight
                    
                    score += brand_similarity / len(outfit_brands)
            
            # Product type similarity based on liked products
            if outfit.products and interaction_patterns.get('preferred_product_types'):
                outfit_types = [p.type.lower() for p in outfit.products if p.type]
                preferred_types = interaction_patterns['preferred_product_types']
                
                total_type_preferences = sum(preferred_types.values())
                if total_type_preferences > 0 and outfit_types:
                    type_similarity = 0
                    for ptype in outfit_types:
                        if ptype in preferred_types:
                            weight = preferred_types[ptype] / total_type_preferences
                            type_similarity += weight
                    
                    score += type_similarity / len(outfit_types)
            
            # Price range similarity to liked products
            if outfit.products and interaction_patterns.get('price_range_preference'):
                price_pref = interaction_patterns['price_range_preference']
                if price_pref['avg'] is not None:
                    outfit_prices = [p.price for p in outfit.products if p.price and p.price > 0]
                    if outfit_prices:
                        avg_outfit_price = sum(outfit_prices) / len(outfit_prices)
                        # Calculate similarity based on how close the price is to user's preferred range
                        if price_pref['min'] <= avg_outfit_price <= price_pref['max']:
                            # Perfect match if within range
                            price_similarity = 1.0
                        else:
                            # Partial match based on distance from preferred average
                            price_diff = abs(avg_outfit_price - price_pref['avg'])
                            max_acceptable_diff = price_pref['avg'] * 0.5  # 50% tolerance
                            price_similarity = max(0, 1 - (price_diff / max_acceptable_diff))
                        
                        score += price_similarity * 0.3  # Weight price similarity
        
        except Exception as e:
            logger_service.error(f"Error scoring interaction history: {str(e)}")
        
        return min(1.0, score)  # Cap at 1.0
    
    def _score_product_level_compatibility(
        self,
        outfit: DatabaseOutfit,
        user_profile_data: Dict[str, Any]
    ) -> float:
        """
        Score outfit based on similarity to individual products the user has liked.
        This provides more granular analysis than just brand/type matching.
        """
        if not outfit.products:
            return 0.0
            
        liked_products = user_profile_data.get('liked_products', [])
        if not liked_products:
            return 0.0
        
        total_compatibility = 0.0
        scored_products = 0
        
        try:
            for outfit_product in outfit.products:
                best_match_score = 0.0
                
                # Compare this outfit product against all liked products
                for liked_product in liked_products:
                    compatibility_score = self._calculate_product_similarity(
                        outfit_product, liked_product
                    )
                    best_match_score = max(best_match_score, compatibility_score)
                
                total_compatibility += best_match_score
                scored_products += 1
            
            return total_compatibility / scored_products if scored_products > 0 else 0.0
            
        except Exception as e:
            logger_service.error(f"Error scoring product compatibility: {str(e)}")
            return 0.0
    
    def _calculate_product_similarity(
        self,
        product1: DatabaseProduct,
        product2: DatabaseProduct
    ) -> float:
        """
        Calculate similarity between two products based on multiple factors.
        
        Returns:
            Float between 0.0 and 1.0 indicating similarity
        """
        similarity_score = 0.0
        factors = 0
        
        try:
            # Brand match (highest weight)
            if product1.brand and product2.brand:
                if product1.brand.lower() == product2.brand.lower():
                    similarity_score += 0.4
                factors += 1
            
            # Type match
            if product1.type and product2.type:
                if product1.type.lower() == product2.type.lower():
                    similarity_score += 0.3
                factors += 1
            
            # Price similarity
            if product1.price and product2.price and product1.price > 0 and product2.price > 0:
                price_diff = abs(product1.price - product2.price)
                max_price = max(product1.price, product2.price)
                price_similarity = max(0, 1 - (price_diff / max_price))
                similarity_score += price_similarity * 0.2
                factors += 1
            
            # Color similarity from titles/descriptions
            colors1 = set()
            colors2 = set()
            
            if product1.title:
                colors1.update(self._extract_colors_from_text(product1.title.lower()))
            if product1.description:
                colors1.update(self._extract_colors_from_text(product1.description.lower()))
                
            if product2.title:
                colors2.update(self._extract_colors_from_text(product2.title.lower()))
            if product2.description:
                colors2.update(self._extract_colors_from_text(product2.description.lower()))
            
            if colors1 and colors2:
                color_overlap = len(colors1.intersection(colors2))
                color_union = len(colors1.union(colors2))
                color_similarity = color_overlap / color_union if color_union > 0 else 0
                similarity_score += color_similarity * 0.1
                factors += 1
            
            # Normalize by number of factors considered
            return similarity_score / factors if factors > 0 else 0.0
            
        except Exception as e:
            logger_service.error(f"Error calculating product similarity: {str(e)}")
            return 0.0
    
    def _score_collection_similarity(
        self,
        outfit: DatabaseOutfit,
        user_profile_data: Dict[str, Any]
    ) -> float:
        """Score based on similarity to items in user's collections."""
        # For now, return a neutral score since collection integration is basic
        # This can be enhanced when collection data fetching is implemented
        return 0.5
    
    def _score_outfit_popularity(self, outfit: DatabaseOutfit) -> float:
        """Score based on outfit popularity and quality metrics."""
        score = 0.5  # Base score
        
        try:
            # Use points if available (assuming higher points = better outfit)
            if hasattr(outfit, 'points') and outfit.points:
                # Normalize points to 0-1 scale (assuming max points of 100)
                points_score = min(outfit.points / 100.0, 1.0)
                score = points_score
            
            # Could add more factors here:
            # - Number of likes the outfit has received
            # - Recency of the outfit
            # - Number of products in the outfit
            # - Quality of product matches
            
        except Exception as e:
            logger_service.error(f"Error scoring outfit popularity: {str(e)}")
        
        return score
    
    def _calculate_profile_strength(self, user_profile_data: Dict[str, Any]) -> float:
        """
        Calculate how much we know about the user (0.0 to 1.0).
        Higher values indicate more personalized recommendations.
        """
        strength = 0.0
        max_strength = 6.0  # Total possible strength points
        
        try:
            preferences = user_profile_data.get('preferences', {})
            
            # Points for explicit preferences
            if preferences.get('positive_styles'):
                strength += 1.0
            if preferences.get('positive_brands'):
                strength += 1.0
            if preferences.get('positive_colors'):
                strength += 1.0
            
            # Points for interaction history
            if user_profile_data.get('liked_outfits'):
                outfit_count = len(user_profile_data['liked_outfits'])
                # More interactions = stronger profile (up to 1.0)
                strength += min(outfit_count / 10.0, 1.0)
            
            if user_profile_data.get('liked_products'):
                product_count = len(user_profile_data['liked_products'])
                strength += min(product_count / 20.0, 1.0)
            
            # Points for collections
            if user_profile_data.get('collection_items'):
                collection_count = len(user_profile_data['collection_items'])
                strength += min(collection_count / 15.0, 1.0)
        
        except Exception as e:
            logger_service.error(f"Error calculating profile strength: {str(e)}")
        
        return min(strength / max_strength, 1.0)

# Create a singleton instance
_recommendation_service = None

def get_recommendation_service() -> RecommendationService:
    """Get the singleton recommendation service instance."""
    global _recommendation_service
    if _recommendation_service is None:
        _recommendation_service = RecommendationService()
    return _recommendation_service
