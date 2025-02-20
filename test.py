from datetime import datetime, timedelta
import uuid
from dotenv import load_dotenv
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, HttpUrl
from serpapi import GoogleSearch
import os
import requests
import json


load_dotenv()

model = OpenAIModel('gpt-4o')

class Product(BaseModel):
    id: str
    query: str
    title: str
    price: str
    link: str
    images: List[str]
    source: str
    type: str
    description: str

class Item(BaseModel):
    type: str
    search_query: str
    products: List[Product]

class Outfit(BaseModel):
    name: str
    description: str
    items: List[Item]

class OutfitPlan(BaseModel):
    user_prompt: str
    outfits: List[Outfit]

class ProductSearch(BaseModel):
    query: str
    product_type: str

class UserPreferences(BaseModel):
    gender: str
    favorite_brands: str

async def go_shopping(product_search: ProductSearch) -> list[Product]:
    """Given a product query, it will search the internet for the desired item based on the query
        and return a list of items found.

    Args:
        queries: An object containing information about the desired product 
    """
    params = {
        "engine": "google_shopping",
        "q": product_search.query,
        "api_key": os.getenv("SERPAPI_API_KEY"),
        "num": 5,
        "hl": "en",
        "gl": "us",
        "location": "United States",
        "direct_link": True
    }

    search = GoogleSearch(params)
    results = search.get_dict()
    shopping_results = results.get("shopping_results", [])

    if shopping_results:

            final_results = {"search_query": product_search.query, "search_results": []}
            items = shopping_results[:5]  # Get the first 5 items

            for item in items:  # Iterate over the first 5 items

                extra_info_url = item.get("serpapi_product_api")
                extra_info_response = requests.get(extra_info_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
                extra_info = extra_info_response.json()
                extra_info_results = extra_info.get("product_results", {})

                print(extra_info)

                result = Product(
                    id=item.get("product_id", "MISSING_PRODUCT_ID"),
                    query=product_search.query,
                    title=item.get("title", "MISSING_PRODUCT_TITLE"),
                    price=item.get("price", "MISSING_PRODUCT_PRICE"),
                    link=item.get("link", "MISSING_PRODUCT_LINK"),
                    images=item.get("thumbnails", ["MISSING_PRODUCT_THUMBNAILS"]),
                    source=item.get("source", "MISSING_PRODUCT_SOURCE"),
                    description=extra_info_results.get("description", "MISSING_PRODUCT_DESCRIPTION"),
                    type=product_search.product_type
                )

                final_results["search_results"].append(result)

            return final_results

system_prompt = f"""
    You are a highly skilled and intuitive personal stylist with a deep understanding of fashion trends, brand aesthetics, and individual style preferences.\n
    Your primary goal is to create personalized outfit plans that align with the user's unique taste, gender, and favorite brands.\n
"""

stylist_agent = Agent(
    model,
    result_type=OutfitPlan,
    deps_type=UserPreferences,
    system_prompt=system_prompt
)

@stylist_agent.system_prompt
async def add_customer_preferences(ctx: RunContext[UserPreferences]) -> str:
    return f"""
    User gender: {ctx.deps.gender}
    User favorite brands: {ctx.deps.favorite_brands}
    """

async def run_test_service(user_prompt: str, user_gender: str, user_favorite_brands: list):
    user_preferences = UserPreferences(
        gender=user_gender,
        favorite_brands=" ".join(user_favorite_brands)
    )

    result = await stylist_agent.run(user_prompt, deps=user_preferences)
    data = result.data

    for outfit in data.outfits:
        for item in outfit.items:
            print(item)
            shopping_results = await go_shopping(ProductSearch(query=item.search_query, product_type=item.type))
            print(shopping_results)
            item.products = shopping_results

    return outfit