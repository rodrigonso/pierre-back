from serpapi import GoogleSearch
import os
from dotenv import load_dotenv
from models import User
import requests
from pydantic import BaseModel
import concurrent.futures
from typing import List, Optional
import time

load_dotenv()

class ProductsResult(BaseModel):
    products: list
    total_results: int
    brand: str
    gender: str = "female" or "male"

class ProductResult(BaseModel):
    id: str
    position: int
    title: str
    brand: str
    price: float
    images: list[str]


class ProductService:
    def __init__(self, user: User):
        self.user = user

    def _extract_price(self, seller) -> float:
        """
        Extracts the price from a string, removing any currency symbols and commas.
        """
        price_str = seller.get("base_price", "")
        if not price_str:
            raise ValueError("Price not found in seller data.")

        return float(price_str.replace("$", "").replace(",", ""))

    def _extract_images(self, product) -> list[str]:
        """
        Extracts image URLs from the product data.
        """
        images = []
        media = product.get("media", [])
        if not media:
            raise ValueError("No media found in product data.")

        images = [img.get("link") for img in media if img.get("link")]
        return images

    def _apply_department_filter(self, filters):

        print(f"{len(filters)} filters found.")
        department_filter = next((f for f in filters if f.get("type") == "Department"), None)

        if not department_filter:
            raise ValueError("Department filter not found in available filters.")

        print(f"Department filter found: {department_filter}")
        department_options = department_filter.get("options", [])

        # Normalize gender options to match user's gender
        normalized_gender = "female" if self.user.gender.lower() in ["female", "woman", "women"] else "male"
        
        gender_option = None
        for option in department_options:
            option_text = option.get("text", "").lower()
            if ("women" in option_text or "female" in option_text) and normalized_gender == "female":
                gender_option = option
                break
            elif ("men" in option_text or "male" in option_text) and normalized_gender == "male":
                gender_option = option
                break

        if not gender_option:
            raise ValueError(f"No matching department filter found for gender: {normalized_gender}")

        print(f"Applying filter for gender: {normalized_gender}")
        filter_link = gender_option.get("serpapi_link", "")

        if not filter_link:
            raise ValueError("No filter link found for the selected department option")

        filtered_response = requests.get(filter_link + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
        filtered_response_parsed = filtered_response.json()

        return filtered_response_parsed.get("shopping_results", [])

    def _extract_product_info(self, product) -> ProductResult:
        product_info_url = product.get("serpapi_product_api", "")

        if not product_info_url:
            raise ValueError("Product info URL not found in the product data.")

        product_info_response = requests.get(product_info_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')

        if product_info_response.status_code != 200:
            raise ValueError("Failed to retrieve product info")

        product_info_parsed = product_info_response.json()

        product_info = product_info_parsed.get("product_results", {})
        seller_info = product_info_parsed.get("sellers_results", {}).get("online_sellers", [])[0] # assume first seller is the best one for now.
        print(f"Product info parsed\n")
        print(f"Seller info parsed\n")

        is_top_quality_store = seller_info.get("top_quality_store", False) # TODO: handle this to select the top quality store instead of the first one.

        if not is_top_quality_store:
            raise ValueError("Product is not from a top quality store.")

        return ProductResult(
            id=product_info.get("product_id", ""),
            position=product.get("position", 0),
            title=product_info.get("title", ""),
            brand=seller_info.get("name", ""),
            price=self._extract_price(seller_info),
            images=self._extract_images(product_info),
            link=seller_info.get("direct_link", ""),
        )

    def _extract_product_info_parallel(self, filtered_results: list) -> List[ProductResult]:
        """
        Extracts product information from a list of products in parallel.
        Returns a list of valid ProductResult objects.
        """
        products = []
        
        # Define a worker function that handles exceptions
        def process_product(product):
            try:
                return self._extract_product_info(product)
            except Exception as e:
                print(f"Error processing product: {e}")
                return None

        # Use ThreadPoolExecutor to process products in parallel
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Submit all products for processing
            future_to_product = {executor.submit(process_product, product): product 
                               for product in filtered_results}

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_product):
                product_result = future.result()
                if product_result:
                    products.append(product_result)

        return products

    def get_products(self):
        start_time = time.time()
        
        brand = self.user.preferred_brands[0] if self.user.preferred_brands else 'zara'

        params = {
            "engine": "google_shopping",
            "q": brand,
            "api_key": os.getenv("SERPAPI_API_KEY"),
            "num": 100, # max is 100 and results are paginated
            "hl": "en",
            "gl": "us",
            "location": "United States",
            "direct_link": True
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        # apply department filter based on user's gender
        filters = results.get("filters", [])
        filtered_results = self._apply_department_filter(filters)

        print(f"Found {len(filtered_results)} products for brand: {brand} and gender: {self.user.gender}")

        # Use the parallel method instead of sequential processing
        products = self._extract_product_info_parallel(filtered_results)

        print(f"Extracted {len(products)} products for brand: {brand} and gender: {self.user.gender}")

        total_duration = time.time() - start_time
        print(f"Total execution time: {total_duration:.2f} seconds")

        return ProductsResult(
            products=products,
            total_results=len(products),
            brand=brand,
            gender=self.user.gender
        )