import openai
import os
import json
import requests
import uuid
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from serpapi import GoogleSearch
from models import Product, ProductResponse, ProductInfo, SellerInfo
from supabase import create_client
import asyncio
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

# Initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "o3-mini"

# Initialize Supabase client
# SUPABASE_URL = os.getenv("SUPABASE_URL")
# SUPABASE_KEY = os.getenv("SUPABASE_KEY")
# supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

class AgentState(Enum):
    ANALYZING_REQUEST = "analyzing_request"
    GATHERING_PREFERENCES = "gathering_preferences"
    CREATING_INITIAL_CONCEPTS = "creating_initial_concepts"
    SEARCHING_PRODUCTS = "searching_products"
    EVALUATING_FITS = "evaluating_fits"
    REFINING_SELECTIONS = "refining_selections"
    FINALIZING_OUTFITS = "finalizing_outfits"
    COMPLETED = "completed"

class UserPreferences(BaseModel):
    gender: str
    preferred_brands: List[str] = Field(default_factory=list)
    style_preferences: List[str] = Field(default_factory=list)
    color_preferences: List[str] = Field(default_factory=list)
    avoid_colors: List[str] = Field(default_factory=list)
    occasion: Optional[str] = None
    season: Optional[str] = None

class OutfitConcept(BaseModel):
    name: str
    description: str
    style_theme: str
    color_palette: List[str]
    required_items: List[Dict[str, str]]  # [{"type": "top", "description": "..."}, ...]
    occasion: str
    season: str

class SearchResult(BaseModel):
    query: str
    products: List[Product]
    item_type: str
    success: bool
    error_message: Optional[str] = None

class OutfitEvaluation(BaseModel):
    concept: OutfitConcept
    found_products: List[Product]
    completeness_score: float  # 0-1
    style_coherence_score: float  # 0-1
    brand_preference_score: float  # 0-1
    overall_score: float       # 0-1
    missing_items: List[str]
    suggestions: List[str]

class StylistAgent:
    def __init__(self):
        self.state = AgentState.ANALYZING_REQUEST
        self.user_preferences = None
        self.user_prompt = ""
        self.num_outfits = 1
        self.concepts = []
        self.search_results = []
        self.evaluations = []
        self.final_outfits = []
        self.iteration_count = 0
        self.max_iterations = 5
        
    def call_openai_api(self, model_name: str, system_content: str, user_content: str, response_format: str = "json_object") -> str:
        """Enhanced OpenAI API call with error handling and image support"""
        try:
            messages = [
                {"role": "system", "content": system_content}
            ]
            
            # Check if the user content contains an image URL
            if "[Image URL]:" in user_content:
                # Split the content by the image URL marker
                parts = user_content.split("[Image URL]:")
                text_content = parts[0].strip()
                image_url = parts[1].strip()
                
                # Create a message with text content
                messages.append({
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": text_content},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        }
                    ]
                })
            else:
                # Standard text-only message
                messages.append({"role": "user", "content": user_content})
            
            response = openai.chat.completions.create(
                model=model_name,
                response_format={"type": response_format},
                messages=messages,
                max_completion_tokens=1000
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return None

    def search_products_tool(self, query: str, item_type: str, max_results: int = 3) -> SearchResult:
        """Tool to search for products using SerpAPI"""
        try:
            params = {
                "engine": "google_shopping",
                "q": query,
                "api_key": os.getenv("SERPAPI_API_KEY"),
                "num": max_results,
                "hl": "en",
                "gl": "us",
                "location": "United States",
                "direct_link": True
            }

            search = GoogleSearch(params)
            results = search.get_dict()
            shopping_results = results.get("shopping_results", [])

            if not shopping_results:
                return SearchResult(
                    query=query,
                    products=[],
                    item_type=item_type,
                    success=False,
                    error_message="No products found"
                )

            products = []
            for item in shopping_results[:max_results]:
                try:
                    # Get detailed product information
                    rich_url = item.get("serpapi_product_api")
                    if rich_url:
                        rich_response = requests.get(rich_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
                        rich_response_parsed = rich_response.json()
                        rich_product_info = self.extract_product_data(rich_response_parsed)
                        
                        product = Product(
                            id=rich_product_info.product.product_id or str(uuid.uuid4()),
                            query=query,
                            title=rich_product_info.product.title or item.get("title", ""),
                            price=item.get("extracted_price", 0),
                            link=rich_product_info.seller.direct_link or item.get("link", ""),
                            images=rich_product_info.product.images or [item.get("thumbnail", "")],
                            source=rich_product_info.seller.seller_name or item.get("source", ""),
                            description=rich_product_info.product.description or "",
                            type=item_type
                        )
                    else:
                        # Fallback to basic item data
                        product = Product(
                            id=str(uuid.uuid4()),
                            query=query,
                            title=item.get("title", ""),
                            price=item.get("extracted_price", 0),
                            link=item.get("link", ""),
                            images=[item.get("thumbnail", "")],
                            source=item.get("source", ""),
                            description="",
                            type=item_type
                        )
                    products.append(product)
                except Exception as e:
                    print(f"Error processing product: {e}")
                    continue

            return SearchResult(
                query=query,
                products=products,
                item_type=item_type,
                success=True
            )

        except Exception as e:
            return SearchResult(
                query=query,
                products=[],
                item_type=item_type,
                success=False,
                error_message=str(e)
            )

    def extract_product_data(self, response_json) -> ProductResponse:
        """Extract product data from SerpAPI response"""
        product_data = response_json.get('product_results', {})
        seller_data = response_json.get('sellers_results', {})
        
        # Extract online sellers info
        online_sellers = seller_data.get('online_sellers', [])
        seller_info = SellerInfo()
        if online_sellers:
            first_seller = online_sellers[0]
            seller_info = SellerInfo(
                seller_name=first_seller.get('name'),
                direct_link=first_seller.get('direct_link'),
                base_price=first_seller.get('base_price'),
                shipping=first_seller.get('additional_price', {}).get('shipping'),
                total_price=first_seller.get('total_price'),
                delivery_info=[detail.get('text') for detail in first_seller.get('details_and_offers', [])]
            )

        # Extract product info
        product_info = ProductInfo(
            product_id=product_data.get('product_id'),
            title=product_data.get('title'),
            description=product_data.get('description'),
            conditions=product_data.get('conditions', []),
            prices=product_data.get('prices', []),
            images=[media.get('link') for media in product_data.get('media', []) if media.get('type') == 'image'],
            extensions=product_data.get('extensions', []),
            sizes=list(product_data.get('sizes', {}).keys())
        )

        return ProductResponse(product=product_info, seller=seller_info)

    def web_search_tool(self, query: str) -> List[str]:
        """Tool to search the web for fashion trends, brand information, etc."""
        try:
            params = {
                "engine": "google",
                "q": query,
                "api_key": os.getenv("SERPAPI_API_KEY"),
                "num": 5,
                "hl": "en",
                "gl": "us"
            }

            search = GoogleSearch(params)
            results = search.get_dict()
            organic_results = results.get("organic_results", [])

            insights = []
            for result in organic_results[:3]:
                insights.append(f"Title: {result.get('title', '')}\nSnippet: {result.get('snippet', '')}")
            
            return insights

        except Exception as e:
            print(f"Error in web search: {e}")
            return []

    def analyze_request(self, user_prompt: str, user_data: Dict[str, Any]) -> UserPreferences:
        """Step 1: Analyze user request and extract preferences"""
        self.state = AgentState.ANALYZING_REQUEST
        self.user_prompt = user_prompt
        
        # Extract basic info from user_data
        gender = user_data.get("user_gender", "")
        preferred_brands = user_data.get("user_preferred_brands", [])
        self.num_outfits = user_data.get("num_of_outfits", 1)
        
        system_content = """
        You are an expert fashion analyst. Analyze the user's outfit request and extract their preferences.
        Pay special attention to:
        - Style preferences (minimalist, boho, streetwear, formal, casual, etc.)
        - Occasion (work, date, party, casual, etc.)
        - Season/weather considerations
        - Color preferences
        - Budget hints
        
        Return a JSON object with the extracted preferences.
        """
        
        user_content = f"""
        User request: {user_prompt}
        User gender: {gender}
        User preferred brands: {', '.join(preferred_brands)}
        
        Extract and analyze the user's preferences from their request. Be specific and detailed.

        IMPORTANT: For the "estimated_budget" field, provide ONLY a numeric value, not a range. 
        For example, use 250 instead of "$200-$300".

        Return JSON with these fields:
        {{
            "style_preferences": ["list of style keywords"],
            "occasion": "primary occasion",
            "season": "season if mentioned",
            "color_preferences": ["preferred colors"],
            "avoid_colors": ["colors to avoid"],
            "estimated_budget": numeric valueonly
        }}
        
        """

        response = self.call_openai_api("gpt-4o", system_content, user_content)
        if response:
            try:
                preferences_data = json.loads(response)

                self.user_preferences = UserPreferences(
                    gender=gender,
                    preferred_brands=preferred_brands,
                    style_preferences=preferences_data.get("style_preferences", []),
                    occasion=preferences_data.get("occasion"),
                    season=preferences_data.get("season"),
                    color_preferences=preferences_data.get("color_preferences", []),
                    avoid_colors=preferences_data.get("avoid_colors", []),
                    budget=preferences_data.get("budget"),
                )
            except Exception as e:
                print(f"Error parsing preferences: {e}")
                # Fallback to basic preferences
                self.user_preferences = UserPreferences(
                    gender=gender,
                    preferred_brands=preferred_brands
                )
        
        return self.user_preferences

    def create_outfit_concepts(self) -> List[OutfitConcept]:
        """Step 2: Create initial outfit concepts based on preferences"""
        self.state = AgentState.CREATING_INITIAL_CONCEPTS
        
        # Get fashion insights from web search
        trend_query = f"{self.user_preferences.season or 'current'} fashion trends {self.user_preferences.gender} {' '.join(self.user_preferences.style_preferences)}"
        trend_insights = self.web_search_tool(trend_query)
        
        system_content = f"""
        You are a creative fashion stylist. Create {self.num_outfits} unique outfit concepts based on the user's preferences.
        Each concept should be detailed and consider current fashion trends.
        User preferences: {self.user_preferences.model_dump()}
        Current fashion insights: {' | '.join(trend_insights[:2])}

        Each outfit should:
        - Be cohesive in style and color
        - Consider the occasion and season
        - Include items from preferred brands when possible
        - Be appropriate for the user's lifestyle

        Return JSON with this structure:
        {{
            "concepts": [
                {{
                    "name": "concept name",
                    "description": "detailed description",
                    "style_theme": "primary style",
                    "color_palette": ["main", "colors"],
                    "required_items": [
                        {{"type": "tops|bottoms|shoes|accessories", "description": "specific item description with brand preference if any"}},
                        ...
                    ],
                    "occasion": "occasion",
                    "season": "season",
                }}
            ]
        }}
        """

        user_content = f"User request: {self.user_prompt}\nCreate outfit concepts that perfectly match these requirements."

        response = self.call_openai_api("o3-mini", system_content, user_content)
        if response:
            try:
                concepts_data = json.loads(response)
                print(f"[StylistAgent] Received concepts: {concepts_data}")
                self.concepts = [OutfitConcept(**concept) for concept in concepts_data["concepts"]]
            except Exception as e:
                print(f"Error parsing concepts: {e}")
                self.concepts = []

        return self.concepts
    
    def search_concept_products(self, concepts: List[OutfitConcept]) -> List[SearchResult]:
        """Step 3: Search for products based on outfit concepts"""
        self.state = AgentState.SEARCHING_PRODUCTS
        search_results = []
        
        # Create search tasks for all required items across all concepts
        search_tasks = []
        for concept in concepts:
            for item in concept.required_items:
                query = f"{item['description']} {concept.color_palette} {concept.occasion} {concept.season}"
                item_type = item["type"]
                search_tasks.append((query, item_type))
        
        # Execute searches in parallel
        with ThreadPoolExecutor(max_workers=min(10, len(search_tasks))) as executor: 
            # Map function to track progress
            def search_with_logging(task):
                query, item_type = task
                print(f"[StylistAgent] Searching for: {query} (Type: {item_type})")
                return self.search_products_tool(query, item_type)
            
            # Execute all search tasks in parallel and collect results
            search_results = list(executor.map(search_with_logging, search_tasks))
        
        self.search_results = search_results
        return search_results

    def evaluate_item_products(self, item_description: str, concept: OutfitConcept, products_data: List[Dict]) -> Dict:
        """Helper method to evaluate products for a single item - can be run in parallel"""
        # Call OpenAI to evaluate the products
        system_content = """
        You are a fashion expert evaluating products against specific requirements.
        Compare the products found to the item description and evaluate how well they match.
        Consider style consistency, color appropriateness, and brand match if applicable.
        """
        
        user_content = f"""
        Item description from outfit concept: "{item_description}"
        Style theme: {concept.style_theme}
        Color palette: {concept.color_palette}
        Occasion: {concept.occasion}
        Season: {concept.season}
        User preferred brands: {self.user_preferences.preferred_brands}
        
        Available products:
        {json.dumps(products_data, indent=2)}
        
        Evaluate and return a JSON with:
        1. The best matching product ID
        2. A score from 0-1 for style match
        3. A score from 0-1 for brand preference match
        4. A brief explanation of the match
        5. Any suggestions for better alternatives
        
        Return format:
        {{
          "best_match_id": "product_id",
          "style_match_score": 0.0-1.0,
          "brand_match_score": 0.0-1.0,
          "match_explanation": "brief explanation",
          "suggestions": "any suggestions for better alternatives"
        }}
        """
        
        response = self.call_openai_api("o3-mini", system_content, user_content)
        if response:
            evaluation = json.loads(response)
            print(f"[StylistAgent] Evaluation response: {evaluation}")
            return evaluation
        return None

    def evaluate_concept_parallel(self, concept: OutfitConcept, categorized_results: Dict) -> OutfitEvaluation:
        """Process a single concept evaluation with parallel product evaluations"""
        found_products = []
        missing_items = []
        completeness_score = 0
        style_coherence_score = 0
        brand_preference_score = 0
        overall_score = 0
        total_items = len(concept.required_items)
        found_items = 0
        suggestions = []
        
        # Create a list of tasks to execute in parallel
        with ThreadPoolExecutor(max_workers=min(10, total_items)) as executor:
            # Create a dictionary to track futures and their corresponding items
            future_to_item = {}
            
            for item in concept.required_items:
                item_type = item["type"]
                item_description = item["description"]
                
                if item_type in categorized_results and categorized_results[item_type]:
                    # Found potential products for this item type
                    results_for_type = categorized_results[item_type]
                    
                    # Prepare product data for evaluation
                    products_data = []
                    for result in results_for_type:
                        for product in result.products:
                            products_data.append({
                                "id": product.id,
                                "title": product.title,
                                "price": product.price,
                                "description": product.description,
                                "source": product.source
                            })
                    
                    # Submit evaluation task to thread pool
                    if products_data:
                        future = executor.submit(
                            self.evaluate_item_products,
                            item_description=item_description,
                            concept=concept,
                            products_data=products_data
                        )
                        future_to_item[future] = {
                            "item_type": item_type,
                            "item_description": item_description,
                            "results_for_type": results_for_type
                        }
                    else:
                        missing_items.append(f"{item_type}: {item_description}")
                else:
                    # No products found for this item type
                    missing_items.append(f"{item_type}: {item_description}")
            
            # Process completed futures as they finish
            for future in future_to_item:
                item_info = future_to_item[future]
                item_type = item_info["item_type"]
                item_description = item_info["item_description"]
                results_for_type = item_info["results_for_type"]
                
                try:
                    evaluation_result = future.result()
                    if evaluation_result:
                        best_match_id = evaluation_result.get("best_match_id")
                        # Find the product with this ID
                        for result in results_for_type:
                            for product in result.products:
                                if product.id == best_match_id:
                                    found_products.append(product)
                                    found_items += 1
                                    
                                    # Add to evaluation metrics
                                    style_coherence_score += evaluation_result.get("style_match_score", 0)
                                    brand_preference_score += evaluation_result.get("brand_match_score", 0)
                                    
                                    if evaluation_result.get("suggestions"):
                                        suggestions.append(f"For {item_type}: {evaluation_result.get('suggestions')}")
                                    
                                    break
                    else:
                        missing_items.append(f"{item_type}: {item_description}")
                except Exception as e:
                    print(f"Error evaluating products for {item_type}: {e}")
                    missing_items.append(f"{item_type}: {item_description}")
        
        # Calculate final scores
        if total_items > 0:
            completeness_score = found_items / total_items
            
            if found_items > 0:
                style_coherence_score = style_coherence_score / found_items
                brand_preference_score = brand_preference_score / found_items
            
            # Overall score is a weighted average
            overall_score = (0.5 * completeness_score) + (0.3 * style_coherence_score) + (0.2 * brand_preference_score)
        
        # Create the evaluation object
        return OutfitEvaluation(
            concept=concept,
            found_products=found_products,
            completeness_score=completeness_score,
            style_coherence_score=style_coherence_score,
            brand_preference_score=brand_preference_score,
            overall_score=overall_score,
            missing_items=missing_items,
            suggestions=suggestions
        )

    def evaluate_products(self, search_results: List[SearchResult]) -> List[OutfitEvaluation]:
        """Step 4: Evaluate product matches and create outfit evaluations using parallel processing"""
        self.state = AgentState.EVALUATING_FITS
        
        # Bucketize search results by item type
        categorized_results = {}
        
        for result in search_results:
            if not result.success:
                continue
                
            item_type = result.item_type
            if item_type not in categorized_results:
                categorized_results[item_type] = []

            categorized_results[item_type].append(result)
        
        # Evaluate concepts in parallel with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(5, len(self.concepts))) as executor:
            future_to_concept = {
                executor.submit(self.evaluate_concept_parallel, concept, categorized_results): concept
                for concept in self.concepts
            }
            
            evaluations = []
            for future in future_to_concept:
                try:
                    evaluation = future.result()
                    evaluations.append(evaluation)
                except Exception as e:
                    print(f"Error evaluating concept: {e}")
        
        self.evaluations = evaluations
        return evaluations

    def run(self, user_prompt: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main execution method for the stylist agent"""
        try:
            print(f"[StylistAgent] Starting outfit generation for: {user_prompt}")
            
            # Step 1: Analyze request and extract preferences
            preferences = self.analyze_request(user_prompt, user_data)
            print(f"[StylistAgent] Analyzed preferences: {preferences.style_preferences}")
            
            # Step 2: Create outfit concepts
            concepts = self.create_outfit_concepts()
            print(f"[StylistAgent] Created {len(concepts)} outfit concepts")

            # Step 3: Search for products based on concepts
            search_results = self.search_concept_products(concepts)
            print(f"[StylistAgent] Retrieved {len(search_results)} search results")
            
            # Step 4: Evaluate products against concepts
            evaluations = self.evaluate_products(search_results)
            print(f"[StylistAgent] Completed {len(evaluations)} outfit evaluations")
            
            # Return final results
            return {
                "user_prompt": user_prompt,
                "outfits": [
                    {
                        "concept": eval.concept.model_dump(),
                        "products": [product.model_dump() for product in eval.found_products],
                        "score": eval.overall_score,
                        "missing_items": eval.missing_items,
                        "suggestions": eval.suggestions
                    } for eval in evaluations
                ],
                "state": self.state.value
            }

        except Exception as e:
            print(f"[StylistAgent] Error: {e}")
            return {
                "error": str(e),
                "user_prompt": user_prompt,
                "outfits": [],
                "state": self.state.value
            }

def run_advanced_stylist_service(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main function to run the advanced stylist agent service
    """
    agent = StylistAgent()
    user_prompt = user_data.get("user_prompt", "")
    
    return agent.run(user_prompt, user_data)



