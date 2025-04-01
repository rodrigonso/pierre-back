import os
import json
import requests
import json
import uuid

from langgraph.graph import START, END
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.adapters.openai import convert_openai_messages
from langchain_openai import ChatOpenAI
from langgraph.graph import Graph
from concurrent.futures import ThreadPoolExecutor, as_completed
from serpapi import GoogleSearch
from dotenv import load_dotenv
from models import ProductResponse, ProductInfo, SellerInfo, Product, Outfit
from supabase import create_client

load_dotenv()

model = ChatOpenAI(model="gpt-4o", max_retries=1)

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def research_agent(user_data: dict):
    """
    Generates a prompt for the 'search_agent' to use during the search phase based on the user's initial prompt.
    :param user_query: The user's initial prompt.
    :return: A prompt for the 'search_agent' to use during the search phase.
    """
    print("[research_agent] starting...")
    user_prompt = user_data["user_prompt"]
    user_gender = user_data["user_gender"]
    user_preferred_brands = user_data["user_preferred_brands"]

    prompt = [{
        "role": "system",
        "content": "As a fashion researcher, your sole purpose is to craft a prompt that will help the 'search_agent' find the best articles for outfit inspirations based on the user's style preferences, gender, budget, and any other user-specific information.  Try to use as few words as possible without losing the context.\n"
    }, {
        "role": "user",
        "content":  f"User gender: {user_gender}.\n"
                    f"User prompt: {user_prompt}.\n"
                    f"User preferred brands: {', '.join(user_preferred_brands)}.\n"
    }]

    converted = convert_openai_messages(prompt)
    response = model.invoke(converted).content
    print("[research_agent] done!")

    return {**user_data, "research_prompt": response}

def search_agent(state: dict):
    """
    Searches the web for articles that are relevant to the user's prompt.
    :param query: The user's initial prompt.
    :return: The search results.
    """
    print("[search_agent] starting...")
    # Remove extra quotes if present
    query = state["research_prompt"].strip("'\"")
    
    search = DuckDuckGoSearchResults()
    results = search.run(query)

    print("[search_agent] done!")

    return {**state, "curated_articles": results}

def curator_agent(state: dict):
    """
    Curate relevant articles from the search results for a given user query.
    :param user_prompt: The user's initial prompt.
    :param search_results: The search results.
    :return: The curated articles.
    """
    print("[curator_agent] starting...")

    user_prompt = state["user_prompt"]
    user_gender = state["user_gender"]
    user_preferred_brands = state["user_preferred_brands"]
    research_prompt = state["research_prompt"]
    search_results = state["search_results"]

    prompt = [{
        "role": "system",
        "content": f"As a fashion curator, your sole purpose is to curate relevant articles from the search results and choose the best ones based on the user's preferences (like gender, brands, etc).\n"
                   f"You should look for more current content and from trusted sources.\n"
    }, {
        "role": "user",
        "content": f"User gender: {user_gender}\n"
                   f"User prompt: {research_prompt}\n"
                   f"User preferred brands: {', '.join(user_preferred_brands)}\n"
                   f"Search results: {search_results}\n"
                   f"Please only return the articles that are relevant to the user.\n"
    }]

    converted = convert_openai_messages(prompt)
    response = model.invoke(converted).content
    print("[curator_agent] done!")

    return {**state, "curated_articles": response}

def stylist_agent(state: dict):
    """
    Creates a wardrobe plan based on the user's prompts and the curated style articles.
    :param state: The state of the graph.
    :return: The wardrobe plan.
    """
    print("[stylist_agent] starting...")

    user_prompt = state["user_prompt"]
    user_gender = state["user_gender"]
    curated_articles = state["curated_articles"]
    research_prompt = state["research_prompt"]
    num_of_outfits = state["num_of_outfits"]

    prompt = [{
        "role": "system",
        "content": f'As a personal fashion stylist, your sole purpose is to create a a list of outfits based on the user\'s style preferences, gender, budget, and any other user-specific information.\n'
                   f'You MUST choose from top/premium brands that are available online and craft your list based on the information found in the curated style articles.\n'
                   f'You need to create {num_of_outfits} complete outfit plans. Each outfit should include a list of items that the \'shopping_agent\' will use to create a search query for the best deals.\n'
                   f'Please return your response in this exact JSON string format:\n'
                   f'{{\n'
                   f'  "outfits": [\n'
                   f'    {{\n'
                   f'      "name": "<outfit name>",\n'
                   f'      "description": "<brief description of the outfit>",\n'
                   f'      "items": [\n'
                   f'        {{\n'
                   f'          "type": "<item type (only possible values: tops, bottoms, shoes, accessories)>",\n'
                   f'          "search_query": "<specific search query for this item>"\n'
                   f'        }}\n'
                   f'      ]\n'
                   f'    }}\n'
                   f'  ]\n'
                   f'}}\n'
                   f'Do not include any other text or formatting in your response. It should only be the JSON string response. Do not wrap the json codes in JSON markers. \n'
    }, {
        "role": "user",
        "content": f"User gender: {user_gender}\n."
                   f"User prompt: {research_prompt}\n."
                   f"Curated articles: {curated_articles}\n."
    }]

    converted = convert_openai_messages(prompt)
    response = model.invoke(converted).content

    print("[stylist_agent] done!")

    return {**state, "wardrobe_plan": response}


def add_products_to_db(products: dict):
    """
    Add product to the Supabase "products" table.
    """
    for product in products:
        try:
            supabase.table("products").insert({
                "id": product.id,
                "query": product.query,
                "title": product.title,
                "price": product.price,
                "link": product.link,
                "images": product.images,
                "source": product.source,
                "description": product.description,
                "type": product.type
            }).execute()
            print(f"[shopping_agent] Added product to Supabase: {product.title}")
        except Exception as e:
            print(f"[shopping_agent] Failed to add product to Supabase: {e}")

def shopping_agent(state: dict) -> dict:
    """
    Creates a shopping list based on the user's prompts and the stylist's outfits.
    Performs searches in parallel and stores results in the Supabase "products" table.
    """
    print("[shopping_agent] starting...")

    wardrobe_plan = state["wardrobe_plan"]

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
    :param state: Contains wardrobe_plan, shopping_results, and user_prompt
    :return: Formatted wardrobe plan with shopping results
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

            # formatted_item = {
            #     "id": item.get("id", uuid.uuid4().hex),
            #     "type": item["type"],
            #     "search_query": search_query,
            #     "products": item_results if item_results else []
            # }

            # formatted_outfit["items"].append(formatted_item)
            formatted_outfit["items"].extend(item_results)

        formatted_output["outfits"].append(formatted_outfit)

    print("[formatter_agent] done!")
    return formatted_output

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

            for item in items:  # Iterate over the first 5 items

                rich_url = item.get("serpapi_product_api")
                rich_response = requests.get(rich_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
                rich_response_parsed = rich_response.json()

                rich_product_info: ProductInfo = extract_product_data(rich_response_parsed)

                product = Product(
                    id=rich_product_info.product.product_id,
                    query=query,
                    title=rich_product_info.product.title,
                    price=rich_product_info.seller.base_price,
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


def run_stylist_service(user_data: dict) -> dict:
    workflow = Graph()

    workflow.add_node("research_agent", research_agent)
    workflow.add_node("search_agent", search_agent)
    workflow.add_node("stylist_agent", stylist_agent)
    workflow.add_node("shopping_agent", shopping_agent)
    workflow.add_node("formatter_agent", formatter_agent)

    workflow.add_edge(START, "research_agent")
    workflow.add_edge("research_agent", "search_agent")
    workflow.add_edge("search_agent", "stylist_agent")
    workflow.add_edge("stylist_agent", "shopping_agent")
    workflow.add_edge("shopping_agent", "formatter_agent")
    workflow.add_edge("formatter_agent", END)

    chain = workflow.compile()

    print("[stylist_service] start.")
    outfits = chain.invoke(user_data)
    print("[stylist_service] exit.")
    return outfits