import logfire
import os
from agents import Agent, Runner, trace, TResponseInputItem, ItemHelpers, function_tool, RunResult
from pydantic import BaseModel
from typing import Literal, Optional
from dataclasses import dataclass
from serpapi import GoogleSearch
import asyncio
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.models import User
from utils.helpers import run_tasks_in_parallel, ParallelExecutionResult

@dataclass
class AnalystResult:
    positive_styles: list[str]
    negative_styles: list[str]
    positive_brands: list[str]
    positive_colors: list[str]
    occasion: Optional[str]
    season: Optional[str]
    budget: Optional[float]
    user_prompt: str

@dataclass
class OutfitProduct:
    title: str
    brand: str
    description: str
    price: float
    link: str
    images: list[str]

@dataclass(frozen=True)
class OutfitItem:
    search_query: str
    color: str
    type: str
    points: int = 0
    product: Optional[OutfitProduct] = None

    def to_str(self) -> str:
        return f"OutfitItem(search_query={self.search_query}, color={self.color}, type={self.type})"
    
@dataclass
class OutfitProductEvaluation:
    score: float
    product_title: str
    reasoning: str

@dataclass
class OutfitConcept:
    name: str
    description: str
    items: list[OutfitItem]
    points: int

    def to_str(self) -> str:
        items_str = ", ".join(item.to_str() for item in self.items)
        return f"OutfitConcept(name={self.name}, description={self.description}, items=[{items_str}], points={self.points})"

@dataclass
class EvaluationFeedback:
    feedback: str
    score: Literal["pass", "needs_improvement", "fail"]

@dataclass
class StylistServiceContext:
    gender: str

    positive_styles: list[str]
    negative_styles: list[str]

    positive_brands: list[str]
    negative_brands: list[str]

    positive_colors: list[str]
    negative_colors: list[str]

    user_prompt: str

class StylistService:
    def __init__(self, user: User, user_prompt: str):
        self.context = StylistServiceContext(
            gender=user.gender,
            positive_styles=user.positive_styles,
            negative_styles=user.negative_styles,
            positive_brands=user.positive_brands,
            negative_brands=user.negative_brands,
            positive_colors=user.positive_colors,
            negative_colors=user.negative_colors,
            user_prompt=user_prompt
        )

    def _fetch_product_details(self, product):
        """Synchronous version of fetch_product_details for use with threading"""
        print(f"Processing product: {product.get('title', 'Unknown')}")

        product_info_url = product.get("serpapi_product_api")
        if not product_info_url:
            raise ValueError(f"No product info URL found for product: {product.get('title', 'Unknown')}")
        
        product_info = requests.get(product_info_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
        product_info = product_info.json()

        product_details = product_info.get("product_results", {})
        product_seller = product_info.get("seller_results", {}).get("online_sellers", [{}])[0]

        return OutfitProduct(
            title=product_details.get("title", "No title"),
            description=product_details.get("description", "No description"),
            brand=product.get("source", "Unknown brand"),
            price=float(product.get("extracted_price", 0.0)),
            link=product_seller.get("direct_link", ""),
            images=[img.get("link") for img in product_details.get("media", []) if img.get("link")],
        )

    def _product_search(self, query: str) -> list[OutfitProduct]:
        """
        Search for a product using in Google Shopping given a query
        """

        params = {
            "engine": "google_shopping",
            "q": query,
            "api_key": os.getenv("SERPAPI_API_KEY"),
            "num": 3,
            "hl": "en",
            "gl": "us",
            "location": "United States",
            "direct_link": True
        }

        search = GoogleSearch(params)
        results = search.get_dict()
        shopping_results = results.get("shopping_results", [])
        if not shopping_results:
            raise ValueError(f"No shopping results found for query: {query}")
        
        # Fetch product details using multithreading
        products = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit all tasks
            future_to_product = {
                executor.submit(self._fetch_product_details, product): product 
                for product in shopping_results[:3]
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_product):
                try:
                    product = future.result()
                    products.append(product)
                except Exception as exc:
                    product_data = future_to_product[future]
                    print(f'Product {product_data.get("title", "Unknown")} generated an exception: {exc}')

        return products
    
    def _update_input(self, new_input: RunResult) -> list[TResponseInputItem]:
        return ItemHelpers.text_message_outputs(new_input.new_items)

    def _fetch_products(self, items: list[OutfitItem]) -> dict[OutfitItem, list[OutfitProduct]]:
        """
        Fetch products for each item in the outfit concept.
        This function is designed to be run in parallel for each item using multithreading.
        Returns a dictionary mapping items to their corresponding products.
        """

        with ThreadPoolExecutor(max_workers=len(items)) as executor:
            # Submit all tasks
            future_to_item = {
                executor.submit(self._product_search, f"{item.search_query} {item.color} {item.type} {self.context.gender}"): item
                for item in items
            }
            
            # Collect results as they complete
            results = {}
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    products = future.result()
                    results[item] = products
                except Exception as exc:
                    print(f'Item {item.to_str()} generated an exception: {exc}')
                    results[item] = []  # Add empty list for failed searches

        return results

    analyst_agent = Agent[StylistServiceContext](
        name="analyst",
        model="gpt-4o", 
        instructions=lambda wrapper, agent: f"""
        ## Analyst Agent Instructions
        You are an expert fashion analyst. Analyze the user's request, improve their prompt and extract outfit specific preferences that may be present in the user's prompt.
        Pay special attention to:
        - Style hints (minimalist, boho, streetwear, formal, casual, etc.)
        - Brand hints (Zara, Levis, Reformation, etc.)
        - Occasion (work, date, party, casual, etc.)
        - Season/weather considerations
        - Color preferences
        - Budget hints

        # Known user information:
        - Positive styles: {wrapper.context.positive_styles}
        - Negative styles: {wrapper.context.negative_styles}
        - Positive brands: {wrapper.context.positive_brands}
        - Negative brands: {wrapper.context.negative_brands}
        - Positive colors: {wrapper.context.positive_colors}
        - Negative colors: {wrapper.context.negative_colors}
        - Gender: {wrapper.context.gender}
        """,
        output_type=AnalystResult,
    )

    stylist_agent = Agent[StylistServiceContext](
        name="stylist",
        model="o4-mini",
        instructions=lambda wrapper, agent: f"""
        ## Stylist Agent Instructions
        You are a fashion stylist. Based on the provided user information below, curate a personalized outfit concept that aligns with the user's preferences and style.

        When creating your outfit concepts, always apply the 7-point rule to ensure balanced and polished styling.
        This rule states that a person should wear no more than 7 visible elements or accessories at one time to avoid looking overdone or cluttered.
        Count these elements when styling:

        ### Guidelines:

        - Aim for 5-7 total elements for a polished look
        - 3-4 elements work well for minimalist or casual styling
        - When one element is very bold or statement-making it will count as 2 points
        - Basic items like plain t-shirts, simple jeans, or neutral shoes typically count as 1 point
        - Wedding rings and simple stud earrings are often considered "neutral" and may not count

        ### When creating outfits:

        - Always mentally count the styling elements in any outfit concept you create
        - If an outfit exceeds 7 points, consider a different combination

        Apply this rule consistently to create harmonious, intentional outfits that look effortlessly put-together rather than overdone.

        ## Known user information:
        - Positive styles: {wrapper.context.positive_styles}
        - Negative styles: {wrapper.context.negative_styles}
        - Positive brands: {wrapper.context.positive_brands}
        - Negative brands: {wrapper.context.negative_brands}
        - Positive colors: {wrapper.context.positive_colors}
        - Negative colors: {wrapper.context.negative_colors}
        - Gender: {wrapper.context.gender}

        ## Important:
        - Do NOT fill out the `products` field, it will be filled later by the shopper agent.
        """,
        output_type=OutfitConcept,
    )

    shopper_agent = Agent[StylistServiceContext](
        name="shopper",
        model="gpt-4o",
        instructions="""
        ## Shopper Agent Instructions
        You are a fashion shopper. 
        You are given an outfit item and a list of products that we found on the internet. Your job is to evaluate the available products against the target outfit item and score them based on how well they match the item.

        Consider:
        - Style coherence
        - Brand alignment
        - Occasion suitability
        - Color harmony
        - Overall aesthetic appeal

        For each product, provide a score from 0 to 10, where 0 means the product does not match the item at all and 10 means it is a perfect match.
        Provide a brief reasoning for your score (1-2 sentences).
        """,
        output_type=list[OutfitProductEvaluation],
    )

    evaluator_agent = Agent[StylistServiceContext](
        name="evaluator",
        instructions="""
        ## Evaluator Agent Instructions
        You are a fashion evaluator. Review the generated outfit and provide feedback.
            Consider:
            - Style coherence
            - Brand alignment
            - Occasion suitability
            - Color harmony
            - Overall aesthetic appeal
        If the outfit meets the user's preferences, provide a positive evaluation and stop execution.
        """,
        output_type=EvaluationFeedback,
    )

    async def run(self) -> None:
        with trace("Pierre"):

            # Initial conversation setup
            input: list[TResponseInputItem] = [{"content": self.context.user_prompt, "role": "user"}]

            analyst_result = await Runner.run(self.analyst_agent, input, context=self.context)
            # Update the user input with the analyst's result
            input = self._update_input(analyst_result)

            while True:

                stylist: RunResult = await Runner.run(self.stylist_agent, input, context=self.context)
                outfit_concept: OutfitConcept = stylist.final_output

                item_to_products = self._fetch_products(outfit_concept.items)

                # Then run the shopper_agent in parallel for each item-products pair
                shopping_eval_tasks = []
                for item in outfit_concept.items:
                    products = item_to_products[item]
                    print(f"Evaluating item: {item.to_str()} against {len(products)} products")

                    # Create input that includes both item and products
                    shopper_input = f"""
## Target Outfit Item:
- Search Query: {item.search_query}
- Color: {item.color}
- Type: {item.type}

## Available Products:
{chr(10).join([f'''{p.title}
- Brand: {p.brand}
- Price: ${p.price}\n''' for p in products])}
"""
                    task = Runner.run(self.shopper_agent, shopper_input, context=self.context)
                    shopping_eval_tasks.append((item, task))

                shopping_eval_results = await asyncio.gather(*[task for _, task in shopping_eval_tasks])

                # Assign results back to items
                updated_items = []
                for i, (item, _) in enumerate(shopping_eval_tasks):
                    # Find the product that matches the evaluation result
                    evaluation_result: list[OutfitProductEvaluation] = shopping_eval_results[i].final_output
                    best_product_score = max(evaluation_result, key=lambda x: x.score, default=None)

                    matching_product = next(
                        (product for product in item_to_products[item] if product.title == best_product_score.product_title),
                        None
                    )

                    # Create new item with the best matching product
                    updated_item = OutfitItem(
                        search_query=item.search_query,
                        color=item.color,
                        type=item.type,
                        product=matching_product,
                        points=item.points
                    )

                    updated_items.append(updated_item)
                    print(f"Chose product: {updated_item.product.title if updated_item.product else 'No products found'}")
                
                # Update the outfit concept with the new items
                outfit_concept = OutfitConcept(
                    name=outfit_concept.name,
                    description=outfit_concept.description,
                    items=updated_items,
                    points=sum(item.points for item in updated_items),
                )

                evaluation: RunResult = await Runner.run(self.evaluator_agent, outfit_concept.to_str(), context=self.context)
                evaluation_feedback: EvaluationFeedback = evaluation.final_output

                print(f"Evaluation feedback: {evaluation_feedback.feedback} (Score: {evaluation_feedback.score})")

                if evaluation_feedback.score == "pass":
                    print("Outfit evaluation passed. Finalizing the outfit concept.")
                    break
                elif evaluation_feedback.score == "needs_improvement":
                    print("Outfit evaluation needs improvement. Revising the outfit concept.")
                    input = self._update_input(evaluation)
                else:
                    print("Outfit evaluation failed. Stopping execution.")
                    return
                
            return outfit_concept



