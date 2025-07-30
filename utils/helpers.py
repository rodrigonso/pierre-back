import requests
from dotenv import load_dotenv
from serpapi import GoogleSearch
import uuid
from pydantic import BaseModel
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from services.logger import get_logger_service
import asyncio
import aiohttp

logger_service = get_logger_service()

load_dotenv()

class SearchWebResult(BaseModel):
    query: str
    results: list[str]
    success: bool
    error_message: str = None

class SearchProduct(BaseModel):
    id: str
    title: str
    brand: str
    description: str
    price: float
    link: str
    images: list[str]

class SearchProductsResult(BaseModel):
    query: str
    products: list[SearchProduct]
    type: str
    success: bool
    error_message: str = None

def search_web(query: str) -> SearchWebResult:
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

        return SearchWebResult(
            query=query,
            results=results,
            success=True
        )

    except Exception as e:
        print(f"Error in web search: {e}")
        return SearchWebResult(
            query=query,
            results=[],
            success=False,
            error_message=str(e)
        )

async def get_product_details_async(session: aiohttp.ClientSession, product) -> SearchProduct:
    """Async version of get_product_details"""
    logger_service.info(f"Fetching rich product data for product: {product.get('title', 'Unknown')}")

    product_info_url = product.get("serpapi_product_api")
    if not product_info_url:
        raise ValueError(f"No product info URL found for product: {product.get('title', 'Unknown')}")
    
    url = product_info_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}'
    
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            product_info = await response.json()
    except asyncio.TimeoutError:
        logger_service.error(f"Timeout fetching product details for: {product.get('title', 'Unknown')}")
        raise
    except Exception as e:
        logger_service.error(f"Error fetching product details: {e}")
        raise

    product_details = product_info.get("product_results", {})
    product_seller = product_info.get("sellers_results", {}).get("online_sellers", [{}])[0]

    return SearchProduct(
        id=product.get("product_id", ""),
        title=product_details.get("title", "No title"),
        description=product_details.get("description", "No description"),
        brand=product.get("source", "Unknown brand"),
        price=float(product.get("extracted_price", 0.0)),
        link=product_seller.get("direct_link", ""),
        images=[img.get("link") for img in product_details.get("media", []) if img.get("link")],
    )

async def search_products_async(query: str, num_results: int = 3) -> SearchProductsResult:
    """
    Async version of search_products that won't block FastAPI threads
    """
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": os.getenv("SERPAPI_API_KEY"),
        "num": num_results,
        "hl": "en",
        "gl": "us",
        "location": "United States",
        "direct_link": True
    }

    logger_service.info(f"Searching for products with query: {query}")

    # This could also be made async if GoogleSearch supports it
    search = GoogleSearch(params)
    results = search.get_dict()
    shopping_results = results.get("shopping_results", [])
    # pagination = results.get("serpapi_pagination", {})

    if not shopping_results:
        raise ValueError(f"No shopping results found for query: {query}")

    # Use async HTTP session for concurrent requests
    async with aiohttp.ClientSession() as session:
        tasks = [
            get_product_details_async(session, product)
            for product in shopping_results[:num_results]
        ]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        products = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                product_data = shopping_results[i]
                logger_service.error(f'Product {product_data.get("title", "Unknown")} generated an exception: {result}')
            else:
                products.append(result)

    return SearchProductsResult(
        query=query,
        products=products,
        type="shopping",
        success=True
    )
