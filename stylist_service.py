from typing import Literal

from langgraph.graph import START, END
from langgraph.prebuilt import ToolNode
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.adapters.openai import convert_openai_messages
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph import Graph
from concurrent.futures import ThreadPoolExecutor, as_completed
from serpapi import GoogleSearch
from typing import List
from dotenv import load_dotenv
import os
import json

model = ChatOpenAI(model="gpt-4o", max_retries=1)
num_of_outfits = 1

load_dotenv()

def research_agent(user_data: dict):
    """
    Generates a prompt for the 'search_agent' to use during the search phase based on the user's initial prompt.
    :param user_query: The user's initial prompt.
    :return: A prompt for the 'search_agent' to use during the search phase.
    """
    print("RESEARCH_AGENT")
    user_prompt = user_data["user_prompt"]
    user_gender = user_data["user_gender"]

    prompt = [{
        "role": "system",
        "content": "As a fashion researcher, your sole purpose is to craft a prompt that will help the 'search_agent' find the best articles for outfit inspirations based on the user's style preferences, gender, budget, and any other user-specific information. Try to use as few words as possible without losing the context. "
    }, {
        "role": "user",
        "content":  f"User gender: {user_gender}\n"
                    f"User prompt: {user_prompt}\n."
    }]

    converted = convert_openai_messages(prompt)
    response = model.invoke(converted).content

    return {"user_prompt": user_prompt, "user_gender": user_gender, "research_prompt": response}

def search_agent(state: dict):
    """
    Searches the web for articles that are relevant to the user's prompt.
    :param query: The user's initial prompt.
    :return: The search results.
    """
    print("SEARCH_AGENT")
    # Remove extra quotes if present
    query = state["research_prompt"].strip("'\"")
    
    search = DuckDuckGoSearchResults()
    results = search.run(query)

    return {"user_prompt": state["user_prompt"], "user_gender": state["user_gender"], "curated_articles": results}

def curator_agent(state: dict):
    """
    Curate relevant articles from the search results for a given user query.
    :param user_prompt: The user's initial prompt.
    :param search_results: The search results.
    :return: The curated articles.
    """
    print("CURATOR_AGENT")
    user_prompt = state["user_prompt"]
    user_gender = state["user_gender"]
    search_results = state["search_results"]

    prompt = [{
        "role": "system",
        "content": f"As a fashion curator, your sole purpose is to curate relevant articles from the search results and choose the best ones based on the user's initial prompt and gender.\n"
                   f"You should look for more current content and from trusted sources.\n"
    }, {
        "role": "user",
        "content": f"User gender: {user_gender}\n"
                   f"User prompt: {user_prompt}\n"
                   f"Search results: {search_results}\n"
                   f"Please only return the articles that are relevant to the user.\n"
    }]

    converted = convert_openai_messages(prompt)
    response = model.invoke(converted).content
    print(response)

    return {"user_prompt": user_prompt, "user_gender": user_gender, "curated_articles": response}

def stylist_agent(state: dict):
    """
    Creates a wardrobe plan based on the user's prompts and the curated style articles.
    :param state: The state of the graph.
    :return: The wardrobe plan.
    """
    print("STYLIST_AGENT")

    user_prompt = state["user_prompt"]
    user_gender = state["user_gender"]
    curated_articles = state["curated_articles"]

    prompt = [{
        "role": "system",
        "content": f'As a personal fashion stylist, your sole purpose is to create a a list of outfits based on the user\'s style preferences, gender, budget, and any other user-specific information. You MUST choose from top/premium brands that are available online and craft your list based on the information found in the curated style articles.\n'
                   f'You need to create {num_of_outfits} complete outfit plans. Each outfit should include a list of items that the \'shopping_agent\' will use to create a search query for the best deals.\n'
                   f'Please return your response in this exact JSON string format:\n'
                   f'{{\n'
                   f'  "outfits": [\n'
                   f'    {{\n'
                   f'      "name": "<outfit name>",\n'
                   f'      "description": "<brief description of the outfit>",\n'
                   f'      "items": [\n'
                   f'        {{\n'
                   f'          "type": "<item type (e.g., top, bottom, shoes)>",\n'
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
                   f"User prompt: {user_prompt}\n."
                   f"Curated articles: {curated_articles}\n."
    }]

    converted = convert_openai_messages(prompt)
    response = model.invoke(converted).content

    return {"user_gender": user_gender, "user_prompt": user_prompt, "wardrobe_plan": response}

def shopping_agent(state: dict):
    """
    Creates a shopping list based on the user's prompts and the stylist's outfits.
    Performs searches in parallel.
    """
    print("SHOPPING_AGENT")
    # Extract search queries from stylist_outfits
    user_prompt = state["user_prompt"]
    user_gender = state["user_gender"]
    wardrobe_plan = state["wardrobe_plan"]

    parsed = json.loads(wardrobe_plan)

    outfits = parsed["outfits"]
    search_queries = [(item["search_query"], item["type"]) for outfit in outfits for item in outfit["items"]]

    # Perform parallel searches using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=50) as executor:
        future_to_query = {
            executor.submit(search_single_item, query, item_type): (query, item_type) 
            for query, item_type in search_queries
        }   

        formatted_results = []
        for future in as_completed(future_to_query):
            result = future.result()
            if result:
                formatted_results.append(result)



    return {"user_gender": state["user_gender"], "user_prompt": state["user_prompt"], "wardrobe_plan": state["wardrobe_plan"], "shopping_results": formatted_results}

def formatter_agent(state: dict):
    """
    Formats the shopping results into a wardrobe plan.
    :param state: Contains wardrobe_plan, shopping_results, and user_prompt
    :return: Formatted wardrobe plan with shopping results
    """
    print("FORMATTER_AGENT")

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
            "items": []
        }

        # Match each item with its shopping result
        for item in outfit["items"]:
            search_query = item["search_query"]
            item_results = shopping_map.get(search_query, [])

            formatted_item = {
                "type": item["type"],
                "search_query": search_query,
                "products": item_results if item_results else []
            }
            formatted_outfit["items"].append(formatted_item)

        formatted_output["outfits"].append(formatted_outfit)

    return formatted_output

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
            final_results = {"search_query": query, "search_results": []}
            items = shopping_results[:5]  # Get the first 5 items
            for item in items:  # Iterate over the first 5 items
                import requests
                import json
                test_url = item.get("serpapi_product_api")
                test_response = requests.get(test_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
                test_formatted = test_response.json()
                test_description = test_formatted.get("product_results", {}).get("description", "Description not found")
                # print(test_description)

                result = {
                    "id": item.get("product_id"),
                    "query": query,
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "link": item.get("link"),
                    "images": item.get("thumbnails"),
                    "source": item.get("source"),
                    "description": test_description,
                    "type": type
                }

                final_results["search_results"].append(result)
            return final_results

    except Exception as e:
        print(f"Error occurred while searching for item: {query}. Error: {e}")
    return None


def run_stylist_service(user_data: dict):
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

    result = chain.invoke(user_data)
    return json.dumps(result)