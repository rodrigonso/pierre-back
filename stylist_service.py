import os
import json
import requests
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from serpapi import GoogleSearch
from dotenv import load_dotenv
from models import ProductResponse, ProductInfo, SellerInfo, Product
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

def call_openai_api(system_content, user_content):
    """Helper function to call OpenAI API with the Responses API approach"""
    try:
        response = openai.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return None

def stylist_agent(user_data: dict):
    """
    Creates a wardrobe plan based on the user's prompts.
    """
    print("[stylist_agent] starting...")

    user_prompt = user_data["user_prompt"]
    user_gender = user_data["user_gender"]
    user_preferred_brands = user_data["user_preferred_brands"]
    num_of_outfits = user_data["num_of_outfits"]

    system_content = f"""
    As a personal stylist, I want you to create a list of outfits based on the user's prompt taking into consideration their style preferences, gender, budget, and any other user-specific information provided.

    Each outfit should also take into consideration the occasion, season and style the user is requesting when creating the outfits. Make sure you choose cohesive colors and pieces that will work well together.

    You MUST choose from top/premium brands that are available online and/or pick the user-specified preferred brands to craft your outfit list.

    Each outfit should be unique and different from the others but follow the same style/theme.

    You need to create {num_of_outfits} complete outfits. Each outfit should include a list of items that the 'shopping_agent' will use to create a search query.

    Your response must be formatted as a valid JSON object with the following structure:
    {{
      "outfits": [
        {{
          "name": "<outfit name>",
          "description": "<brief description of the outfit>",
          "items": [
            {{
              "type": "<item type (only possible values: tops, bottoms, shoes, accessories)>",
              "search_query": "<specific search query for this item>"
            }}
          ]
        }}
      ]
    }}
    """

    user_content = f"User gender: {user_gender}\n" \
                  f"User prompt: {user_prompt}\n" \
                  f"User preferred brands: {', '.join(user_preferred_brands)}\n"

    response = call_openai_api(system_content, user_content)
    print("[stylist_agent] done!")

    return {**user_data, "wardrobe_plan": response}

def extract_product_data(response_json) -> ProductResponse:
    """
    Extract relevant product and seller information from the API response
    """
    product_data = response_json.get('product_results', {})
    seller_data = response_json.get('sellers_results', {})
    
    # Extract online sellers info
    online_sellers = seller_data.get('online_sellers', [])
    seller_info = SellerInfo()
    if online_sellers:
        # Grab the first seller - we are assuming 1st seller is the best
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

def search_single_item(query: str, type: str) -> dict:
    """
    Perform a single search for an item
    """
    try:
        params = {
            "engine": "google_shopping",
            "q": query,
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
            final_products = {"search_query": query, "search_results": []}
            items = [shopping_results[0]]  # Get the first item and keep it as an array

            for item in items:

                rich_url = item.get("serpapi_product_api")
                rich_response = requests.get(rich_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
                rich_response_parsed = rich_response.json()

                rich_product_info: ProductResponse = extract_product_data(rich_response_parsed)

                product = Product(
                    id=rich_product_info.product.product_id,
                    query=query,
                    title=rich_product_info.product.title,
                    price=item.get("extracted_price", 0),
                    link=rich_product_info.seller.direct_link,
                    images=rich_product_info.product.images,
                    source=rich_product_info.seller.seller_name,
                    description=rich_product_info.product.description,
                    type=type
                )

                final_products["search_results"].append(product)
            return final_products

    except Exception as e:
        print(f"Error occurred while searching for item: {query}. Error: {e}")
    return None

def shopping_agent(state: dict) -> dict:
    """
    Creates a shopping list based on the user's prompts and the stylist's outfits.
    Performs searches in parallel and stores results in the Supabase "products" table.
    """
    print("[shopping_agent] starting...")

    wardrobe_plan = state["wardrobe_plan"]
    
    # Parse the wardrobe plan
    parsed = json.loads(wardrobe_plan)
    outfits = parsed["outfits"]
    search_queries = [(item["search_query"], item["type"]) for outfit in outfits for item in outfit["items"]]

    # Perform parallel searches using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=100) as executor:
        future_to_query = {
            executor.submit(search_single_item, query, item_type): (query, item_type) for query, item_type in search_queries
        }

        formatted_results = []
        for future in as_completed(future_to_query):
            product_result = future.result()
            if product_result:
                formatted_results.append(product_result)

    print("[shopping_agent] done!")

    return {**state, "shopping_results": formatted_results}

def formatter_agent(state: dict):
    """
    Formats the shopping results into a wardrobe plan.
    """
    print("[formatter_agent] starting...")

    wardrobe_plan = json.loads(state["wardrobe_plan"])
    shopping_results = state["shopping_results"]
    user_prompt = state["user_prompt"]

    # Create a mapping of search queries to shopping results
    shopping_map = {result["search_query"]: result["search_results"] for result in shopping_results}

    # Create formatted output
    formatted_output = {
        "user_prompt": user_prompt,
        "outfits": []
    }

    # Map shopping results to each outfit
    for outfit in wardrobe_plan["outfits"]:
        formatted_outfit = {
            "name": outfit["name"],
            "description": outfit["description"],
            "query": user_prompt,
            "items": []
        }

        # Match each item with its shopping result
        for item in outfit["items"]:
            search_query = item["search_query"]
            item_results = shopping_map.get(search_query, [])
            formatted_outfit["items"].extend(item_results)

        formatted_output["outfits"].append(formatted_outfit)

    print("[formatter_agent] done!")
    return formatted_output

def run_stylist_service(user_data: dict) -> dict:
    """
    Run the stylist service without using LangGraph or LangChain.
    Simply execute the agents in sequence.
    """
    print("[stylist_service] start.")
    
    # Execute agents in sequence
    state = stylist_agent(user_data)
    state = shopping_agent(state)
    result = formatter_agent(state)
    
    print("[stylist_service] exit.")
    return result