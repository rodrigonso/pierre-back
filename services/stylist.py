from agents import Agent, Runner, trace, TResponseInputItem, ItemHelpers, RunResult
from pydantic import BaseModel
from typing import Literal, Optional, List
from dataclasses import dataclass
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.models import User
from utils.helpers import SearchProduct, search_products_async, SearchProductsResult
from services.logger import get_logger_service
from openai import OpenAI
import os
from prompts import classifier, evaluator, product_stylist, shopper, stylist, analyst, product_evaluator

logger_service = get_logger_service()

@dataclass
class UserIntentResult:
    intent: Literal["generate_outfit", "find_products"]
    reasoning: str

@dataclass
class AnalystResult:
    positive_styles: list[str]
    negative_styles: list[str]
    positive_brands: list[str]
    negative_brands: list[str]
    positive_colors: list[str]
    negative_colors: list[str]
    occasion: Optional[str]
    season: Optional[str]
    budget: Optional[float]
    user_prompt: str

@dataclass(frozen=True)
class OutfitItem:
    search_query: str
    color: str
    type: Literal["top", "bottom", "dress", "outerwear", "shoes", "accessories", "jewelry"]
    style: Literal["casual", "formal", "boho", "streetwear", "minimalist", "vintage", "sporty", "chic"]
    reasoning: str
    points: int = 0
    product: Optional[SearchProduct] = None

    def to_str(self) -> str:
        return f"""
        ### Outfit Item Details
        - Search query: {self.search_query}
        - Color: {self.color}
        - Type: {self.type}
        """

@dataclass
class OutfitConcept:
    name: str
    description: str
    items: list[OutfitItem]
    points: int
    style: Literal["casual", "formal", "boho", "streetwear", "minimalist", "vintage", "sporty"]

    def to_str(self) -> str:
        """Convert the outfit concept to a markdown formatted string."""
        items_md = "\n".join([
            f"#### Item {i+1}: {item.type.title()}\n"
            f"- **Search Query:** {item.search_query}\n"
            f"- **Color:** {item.color}\n"
            f"- **Points:** {item.points}\n"
            f"- **Reasoning:** {item.reasoning}\n"
            + (f"- **Product:** {item.product.title} by {item.product.brand} (${item.product.price})\n" if item.product else "- **Product:** Not selected\n")
            for i, item in enumerate(self.items)
        ])
        
        return f"""# {self.name}
    ## Description
    {self.description}

    ## Total Style Points: {self.points}

    ## Outfit Items
    {items_md}"""
    
@dataclass
class OutfitProductEvaluation:
    score: float
    product_id: str
    product_title: str
    reasoning: str

@dataclass
class ProductEvaluation:
    score: float
    product_title: str
    reasoning: str

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

@dataclass
class ProductStylistResponse:
    search_query: str
    color: str
    brand: str
    style: Literal["casual", "formal", "boho", "streetwear", "minimalist", "vintage", "sporty"]
    type: Literal["top", "bottom", "dress", "outerwear", "shoes", "accessories", "jewelry"]
    points: int
    reasoning: str

class Product(BaseModel):
    id: str
    type: str
    title: str
    brand: str
    price: float
    link: str
    images: list[str]
    description: str
    search_query: str
    points: int
    color: str
    style: str

class Outfit(BaseModel):
    id: Optional[int]
    name: str
    description: str
    products: list[Product]
    image_url: Optional[str] = None
    user_prompt: str
    points: int
    style: str

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
        # Initialize OpenAI client for intent determination
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ============= Helpers ============
    def _update_input(self, new_input: RunResult) -> list[TResponseInputItem]:
        return ItemHelpers.text_message_outputs(new_input.new_items)

    async def _fetch_products(self, items: list[OutfitItem], num_results: int = 3) -> dict[OutfitItem, list[Product]]:
        """
        Fetch products for each item in the outfit concept.
        This function uses the async search_products_async function to fetch products
        for each outfit item concurrently without blocking the event loop.
        Returns a dictionary mapping items to their corresponding products.
        """

        # Create async tasks that run the async search_products_async function
        async def fetch_single_item(item: OutfitItem) -> tuple[OutfitItem, list[Product]]:
            try:
                # search_query = f"{item.search_query} {item.color} {item.type} {self.context.gender}"
                search_query = f"{item.search_query}"
                # Run the async search_products_async function
                result: SearchProductsResult = await search_products_async(search_query, num_results)
                return item, result.products
            except Exception as exc:
                logger_service.error(f'Item {item.search_query} generated an exception: {exc}')
                return item, []  # Return empty list for failed searches

        # Execute all tasks concurrently
        tasks = [fetch_single_item(item) for item in items]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert list of tuples back to dictionary
        results = {}
        for result in results_list:
            if isinstance(result, Exception):
                logger_service.error(f'Task failed with exception: {result}')
                continue
            item, products = result
            results[item] = products

        return results

    def _convert_outfit_concept_to_outfit(self, outfit_concept: OutfitConcept) -> Outfit:
        """
        Convert an OutfitConcept to an Outfit model.
        This is a utility function to convert the final output of the stylist service.
        """
        pydantic_products = []
        for item in outfit_concept.items:
            if item.product is not None:
                # Convert helper Product to Pydantic Product
                pydantic_product = Product(
                    id=item.product.id,
                    type=item.type,
                    search_query=item.search_query,
                    color=item.color,
                    style=item.style,
                    points=item.points,
                    title=item.product.title,
                    brand=item.product.brand,
                    price=item.product.price,
                    link=item.product.link,
                    images=item.product.images,
                    description=item.product.description
                )
                pydantic_products.append(pydantic_product)

        return Outfit(
            id=None,
            points=outfit_concept.points,
            name=outfit_concept.name,
            description=outfit_concept.description,
            products=pydantic_products,
            image_url=None,  # No image URL available in current outfit concept
            user_prompt=self.context.user_prompt,
            style=outfit_concept.style,
        )

# ============= Agents ============
    analyst_agent = Agent[StylistServiceContext](
        name="analyst",
        model="gpt-4o-mini", 
        instructions=lambda wrapper, agent: analyst.get_prompt(wrapper.context),
        output_type=AnalystResult,
    )

    stylist_agent = Agent[StylistServiceContext](
        name="stylist",
        model="gpt-4o",
        instructions=lambda wrapper, agent: stylist.get_prompt(wrapper.context),
        output_type=OutfitConcept,
    )

    shopper_agent = Agent[StylistServiceContext](
        name="shopper",
        model="gpt-4o-mini",
        instructions=lambda wrapper, agent: shopper.get_prompt(wrapper.context),
        output_type=list[OutfitProductEvaluation],
    )

    evaluator_agent = Agent[StylistServiceContext](
        name="evaluator",
        instructions=lambda wrapper, agent: evaluator.get_prompt(wrapper.context),
        output_type=EvaluationFeedback,
    )

    intent_agent = Agent[StylistServiceContext](
        name="intent_classifier",
        model="gpt-4.1-nano",
        instructions=lambda wrapper, agent: classifier.get_prompt(wrapper.context),
        output_type=UserIntentResult,
    )

    product_stylist_agent = Agent[StylistServiceContext](
        name="product_stylist",
        model="gpt-4.1-nano",
        instructions=lambda wrapper, agent: product_stylist.get_prompt(wrapper.context),
        output_type=ProductStylistResponse,
    )

    product_evaluator_agent = Agent[StylistServiceContext](
        name="product_evaluator",
        model="gpt-4.1-nano",
        instructions=lambda wrapper, agent: product_evaluator.get_prompt(wrapper.context),
        output_type=list[ProductEvaluation],
    )

    async def generate_outfit(self) -> Outfit:
        with trace("Pierre_outfit_stylist"):

            # Initial conversation setup
            input: list[TResponseInputItem] = [{"content": self.context.user_prompt, "role": "user"}]

            analyst_result = await Runner.run(self.analyst_agent, input, context=self.context)
            input = self._update_input(analyst_result)

            # Extend the context with the analyst's output without overriding existing values
            self.context.positive_styles.extend(analyst_result.final_output.positive_styles)
            self.context.negative_styles.extend(analyst_result.final_output.negative_styles)
            self.context.positive_brands.extend(analyst_result.final_output.positive_brands)
            self.context.negative_brands.extend(analyst_result.final_output.negative_brands)
            self.context.positive_colors.extend(analyst_result.final_output.positive_colors)
            self.context.negative_colors.extend(analyst_result.final_output.negative_colors)

            while True:

                stylist: RunResult = await Runner.run(self.stylist_agent, analyst_result.final_output.user_prompt, context=self.context)
                outfit_concept: OutfitConcept = stylist.final_output

                item_to_products: dict[OutfitItem, list[Product]] = {}
                try:
                    item_to_products = await self._fetch_products(outfit_concept.items, num_results=10)
                except Exception as e:
                    logger_service.error(f"Error fetching products: {e}")
                    # If fetching products fails, we can either retry or break the loop
                    # For now, let's just log the error and break
                    break

                # Then run the shopper_agent in parallel for each item-products pair
                shopping_eval_tasks = []
                for item in outfit_concept.items:
                    products = item_to_products[item]
                    logger_service.debug(f"Evaluating products for item {item.search_query}: {[p.title for p in products]}")
                    # Create input that includes both item and products
                    products_formatted = "\n".join([
                        f"""### {i+1}. {p.id}
- **Title:** {p.title}
- **Brand:** {p.brand}
- **Price:** ${p.price}
- **Description:** {p.description[:100]}{'...' if len(p.description) > 100 else ''}
""" for i, p in enumerate(products)])

                    shopper_input = f"""
## Target Outfit Item:
- Search Query: {item.search_query}
- Color: {item.color}
- Type: {item.type}
- Style: {item.style}

## Available Products:
{products_formatted}
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
                        (product for product in item_to_products[item] if product.id == best_product_score.product_id),
                        None
                    )

                    # Create new item with the best matching product
                    updated_item = OutfitItem(
                        search_query=item.search_query,
                        color=item.color.lower(),
                        style=item.style.lower(),
                        type=item.type.lower(),
                        product=matching_product,
                        points=item.points,
                        reasoning=item.reasoning
                    )

                    updated_items.append(updated_item)
                    logger_service.debug(f"Evaluator chose product: {updated_item.product.title if updated_item.product else 'No matching products found'} for item {item.search_query}")
                
                # Update the outfit concept with the new items
                outfit_concept = OutfitConcept(
                    name=outfit_concept.name,
                    description=outfit_concept.description,
                    style=outfit_concept.style,
                    items=updated_items,
                    points=sum(item.points for item in updated_items),
                )

                # evaluation: RunResult = await Runner.run(self.evaluator_agent, outfit_concept.to_str(), context=self.context)
                # evaluation_feedback: EvaluationFeedback = evaluation.final_output

                # print(f"Evaluation feedback: {evaluation_feedback.feedback} (Score: {evaluation_feedback.score})")

                # if evaluation_feedback.score == "pass":
                #     print("Outfit evaluation passed. Finalizing the outfit concept.")
                #     break
                # elif evaluation_feedback.score == "needs_improvement":
                #     print("Outfit evaluation needs improvement. Revising the outfit concept.")
                #     input = self._update_input(evaluation)
                # else:
                #     print("Outfit evaluation failed. Stopping execution.")
                #     return
                break # skip evaluation for now, we can add it later
        
        return self._convert_outfit_concept_to_outfit(outfit_concept)

    async def determine_user_intent(self) -> str:
        """
        Determine the user's intent based on their prompt.
        
        This method uses the intent_agent to classify the user's request into
        either "generate_outfit" or "find_products".
        
        Returns:
            str: The determined user intent ("generate_outfit" or "find_products")        """
        input: list[TResponseInputItem] = [{"content": self.context.user_prompt, "role": "user"}]
        result = await Runner.run(self.intent_agent, input, context=self.context)
        return result.final_output.intent

    async def search_for_products(self, num_items: int, evaluate_results: bool = False) -> List[Product]:
        """
        Generate and find products based on user request.
        
        This method handles product search and discovery when the user's intent 
        is to find specific products rather than generate complete outfits.
        
        Returns:
            List[Product]: List of products matching the user's request
        """

        with trace("Pierre_product_stylist"):
            logger_service.info(f"Understanding user request: {self.context.user_prompt}")

            input: list[TResponseInputItem] = [{"content": self.context.user_prompt, "role": "user"}]
            product_shopper_result: RunResult = await Runner.run(self.product_stylist_agent, input, context=self.context)
            shopper_result: ProductStylistResponse = product_shopper_result.final_output

            # Create a temporary OutfitItem to use our existing product fetching logic
            temp_item = OutfitItem(
                search_query=shopper_result.search_query,
                color=shopper_result.color, 
                type=shopper_result.type, 
                style=shopper_result.style, 
                reasoning=""
            )

            logger_service.info(f"Generated search query: {temp_item.search_query} for color: {temp_item.color}, type: {temp_item.type}, style: {temp_item.style}")
            # Fetch products using existing infrastructure
            item_to_products = await self._fetch_products([temp_item], num_items)
            found_products = item_to_products.get(temp_item, [])
            
            if not found_products:
                logger_service.info(f"No products found for search query: {shopper_result.search_query}")
                return []

            logger_service.debug(f"Found {len(found_products)} products for evaluation")

            # If we are not evaluating results, return the found products directly
            if not evaluate_results:
                logger_service.info(f"Returning {len(found_products)} products without evaluation")
                # Convert SearchProduct to Product model
                result_products = [
                    Product(
                        id=product.id,
                        type=shopper_result.type,
                        title=product.title,
                        brand=product.brand,
                        price=product.price,
                        link=product.link,
                        images=product.images,
                        description=product.description,
                        search_query=shopper_result.search_query,
                        points=shopper_result.points,
                        color=shopper_result.color,
                        style=shopper_result.style
                ) for product in found_products]
                logger_service.info(f"Returning {len(result_products)} products")
                return result_products

            # Create parallel evaluation tasks for each product
            evaluation_tasks = []
            for product in found_products:
                evaluator_input = f"""
## User Request:
{self.context.user_prompt}

## Target Item Criteria:
- Search Query: {shopper_result.search_query}
- Color: {shopper_result.color}
- Brand: {shopper_result.brand}
- Style: {shopper_result.style}
- Type: {shopper_result.type}

## Product to Evaluate:
- Title: {product.title}
- Brand: {product.brand}
- Price: ${product.price}
- Description: {product.description[:200]}...
"""
                # Create evaluation task for this specific product
                task = Runner.run(self.product_evaluator_agent, evaluator_input, context=self.context)
                evaluation_tasks.append((product, task))

            logger_service.debug(f"Created {len(evaluation_tasks)} evaluation tasks for products")
            # Execute all evaluation tasks in parallel
            evaluation_results = await asyncio.gather(*[task for _, task in evaluation_tasks])

            logger_service.debug(f"Completed all product evaluations")
            
            # Flatten the results since each evaluation returns a list with one ProductEvaluation
            evaluations = []
            for i, (product, _) in enumerate(evaluation_tasks):
                product_evaluations = evaluation_results[i].final_output
                # Each result should contain exactly one evaluation for the specific product
                if product_evaluations:
                    evaluations.extend(product_evaluations)

            # Sort evaluations by score (highest first) and filter out low scores
            sorted_evaluations = sorted(evaluations, key=lambda x: x.score, reverse=True)
            logger_service.debug(f"Sorted evaluations: {[f'{eval.product_title}: {eval.score}' for eval in sorted_evaluations]}")
            high_scoring_evaluations = [eval for eval in sorted_evaluations if eval.score >= 6.0]  # Only products with score 6 or higher

            logger_service.debug(f"Found {len(high_scoring_evaluations)} high-scoring products")

            # Convert to Product models
            result_products = []
            for evaluation in high_scoring_evaluations:
                # Find the matching product
                matching_product = next((product for product in found_products if product.title == evaluation.product_title), None)
                logger_service.debug(f"Matching product: {evaluation.product_title} with score {evaluation.score}")
                if matching_product:
                    # Convert SearchProduct to Product model
                    product = Product(
                        id=matching_product.id,
                        type=shopper_result.type,
                        title=matching_product.title,
                        brand=matching_product.brand,
                        price=matching_product.price,
                        link=matching_product.link,
                        images=matching_product.images,
                        description=matching_product.description,
                        search_query=shopper_result.search_query,
                        points=shopper_result.points,
                        color=shopper_result.color,
                        style=shopper_result.style
                    )
                    result_products.append(product)

            logger_service.info(f"Returning {len(result_products)} evaluated products")
            return result_products

