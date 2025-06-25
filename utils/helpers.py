import requests
from dotenv import load_dotenv
from serpapi import GoogleSearch
import uuid
from pydantic import BaseModel
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def get_product_details(product):
    print(f"Getting product details: {product.get('title', 'Unknown')}")

    product_info_url = product.get("serpapi_product_api")
    if not product_info_url:
        raise ValueError(f"No product info URL found for product: {product.get('title', 'Unknown')}")
    
    product_info = requests.get(product_info_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
    product_info = product_info.json()

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

def search_products(query: str) -> list[SearchProduct]:
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

    print(f"Searching for products with query: {query}")

    search = GoogleSearch(params)
    results = search.get_dict()
    shopping_results = results.get("shopping_results", [])
    if not shopping_results:
        raise ValueError(f"No shopping results found for query: {query}")
    
    # Get product details in parallel
    products = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        # Submit all tasks
        future_to_product = {
            executor.submit(get_product_details, product): product
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
