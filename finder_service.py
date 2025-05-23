import os
import json
import requests
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from serpapi import GoogleSearch
from dotenv import load_dotenv
from models import ProductMatch, Product
from supabase import create_client
import openai

load_dotenv()

# Initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "o3-mini"

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


async def find_item_by_image_url(image_url: str) -> str:
    try:
        params = {
            "engine": "google_lens",
            "url": image_url,
            "api_key": os.getenv("SERPAPI_API_KEY"),
            "num": 5,
            "hl": "en",
            "gl": "us",
            "location": "United States",
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        product_page_token = results.get("products_page_token", "")

        if not product_page_token:
            raise ValueError("Error: 'products_page_token' is empty in the results.")

    except Exception as e:
        print(f"Error during image search: {e}")
        product_page_token = ""
    
    return product_page_token


async def get_product_matches(product_page_token: str) -> list[Product]:
    try:
        params = {
            "engine": "google_lens",
            "page_token": product_page_token,
            "api_key": os.getenv("SERPAPI_API_KEY"),
            "hl": "en",
            "gl": "us",
            "location": "United States",
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        product_matches = results.get("visual_matches", [])

        if not product_matches:
            raise ValueError("Error: 'product_matches' is empty in the results.")
        
        result: list[Product] = []

        for match in product_matches[:10]:  # Limit to the first 10 matches
            product = {
                "id": str(uuid.uuid4()),
                "title": match.get("title", ""),
                "link": match.get("link", ""),
                "source": match.get("source", ""),
                "price": match.get("price", {}).get("extracted_value", 0),
                "images": [match.get("image", "")],
                "description": match.get("description", ""),
                "type": match.get("type", ""),
            }

            result.append(Product(**product))
        return result
    
    except Exception as e:
        print(f"Error during product matches retrieval: {e}")
        return []


async def run_finder_service(image_url) -> list[Product]:
    print("[finder_service] start.")

    product_page_token: str = await find_item_by_image_url(image_url)
    product_matches: list[Product] = await get_product_matches(product_page_token)

    if not product_matches:
        return []

    print("[finder_service] exit.")
    return product_matches