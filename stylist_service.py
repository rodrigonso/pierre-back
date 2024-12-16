from typing import TypedDict, List, Dict, Any, Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import AnyMessage
from langgraph.graph import MessagesState, START, StateGraph, END
from langgraph.types import Command
from serpapi import GoogleSearch

from dotenv import load_dotenv
import json
import os

load_dotenv()


model = ChatOpenAI(model="gpt-4o")

def find_clothing_items(query: str):
    """
    Find clothing items based on a query.
    """
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": os.getenv("SERPAPI_API_KEY"),
        "num": 1,
        "hl": "en",
        "gl": "us",
        "location": "United States"
    }

    search = GoogleSearch(params)
    results = search.get_dict()
    shopping_results = results["shopping_results"]

    formatted_results = []
    for item in shopping_results:
        formatted_item = {
            "title": item["title"],
            "price": item["price"],
            "product_link": item["product_link"],
            "product_image": item.get("thumbnails", [item.get("thumbnail")])[0] if item.get("thumbnails") or item.get("thumbnail") else None
        }

        formatted_results.append(formatted_item)

    # print(formatted_results)
    return formatted_results

# Define a helper for each of the agent nodes to call
def call_llm(messages: list[AnyMessage], target_agent_nodes: list[str]):
    """Call LLM with structured output to get a natural language response as well as a target agent (node) to go to next.

    Args:
        messages: list of messages to pass to the LLM
        target_agents: list of the node names of the target agents to navigate to
    """
    json_schema = {
        "name": "Response",
        "parameters": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "A human readable response to the original question. If you need to search for items, include 'SEARCH: <query>' in your response. Will be streamed back to the user.",
                },
                "goto": {
                    "enum": [*target_agent_nodes, "__end__"],
                    "type": "string",
                    "description": "The next agent to call, or __end__ if the user's query has been resolved. Must be one of the specified values.",
                },
                "should_search": {
                    "type": "boolean",
                    "description": "Set to true if your response includes a SEARCH: query that should be executed.",
                }
            },
            "required": ["response", "goto", "should_search"],
        },
    }
    response = model.with_structured_output(json_schema).invoke(messages)
    return response


def stylist_advisor(
    state: MessagesState,
) -> Command[Literal["shopping_advisor", "__end__"]]:
    system_prompt = (
        "You are a personal stylist that creates curated outfit recommendations based on user preferences and budget. "
        "Your task is to craft 1 complete outfit that match the user's style, season, and budget constraints. "
        
        "For each outfit, follow this exact format:"
        "1. Outfit Name: A descriptive title for the look"
        "2. Style Description: Brief explanation of the outfit's aesthetic and occasion"
        "3. Total Budget: Breakdown of expected costs"
        "4. Required Items: List each item needed with specific search terms in brackets, e.g.:"
        "   - [beige wool coat parisian style]"
        "   - [black turtleneck sweater merino wool]"
        "   - [high waisted straight leg jeans dark wash]"
        
        "Guidelines:"
        "- Use specific, searchable terms in brackets for each item"
        "- Include color, material, and style details in search terms"
        "- Stay within the user's total budget"
        "- Ensure items are seasonally appropriate"
        "- Focus on versatile, mix-and-match pieces"
        "- Use the user's preferred brands if provided"
        
        "When you need to find real items:"
        "1. First provide your outfit recommendations with bracketed search terms"
        "2. Then say 'I'll ask shopping_advisor to find these items'"
        "3. Set goto='shopping_advisor'"
        
        "If you have complete recommendations with real items, set goto='__end__'"
        
        "Never mention other agents directly in your response to the user."
    )
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    target_agent_nodes = ["shopping_advisor"]
    response = call_llm(messages, target_agent_nodes)
    print("STYLIST_ADVISOR response: ", response)
    print("\n------------------------------------\n")

    ai_msg = {"role": "ai", "content": response["response"], "name": "shopping_advisor"}
    # handoff to another agent or halt
    return Command(goto=response["goto"], update={"messages": ai_msg})

def shopping_advisor(
    state: MessagesState,
) -> Command[Literal["stylist_advisor", "wardrobe_finalizer"]]:
    system_prompt = (
        "You are a shopping expert that helps find real clothing items based on the stylist's recommendations from the worlds top/premium brands. "
        "When you receive outfit recommendations with bracketed search terms like [black turtleneck sweater merino wool], "
        "your job is to:"
        "1. Extract each bracketed search term"
        "2. For each term, include 'SEARCH: ' followed by the search term"
        "3. After getting search results, analyze them and provide a curated selection"
        "4. Match items to the original outfit recommendations"
        "5. Consider the user's budget when recommending items"
        
        "Format your response like this:"
        "For [search term]:"
        "- Item Name: (price)"
        "- Link: product_link"
        "- Image: product_image"
        
        "After finding items for all searches:"
        "1. Summarize the complete outfits with real items"
        "2. Provide total cost for each outfit"
        "3. Set goto='__end__' if all items are found"
        "4. Set goto='stylist_advisor' if you need new recommendations"
        
        "Set should_search=true when your response includes 'SEARCH:' queries."
    )
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    target_agent_nodes = ["stylist_advisor", "wardrobe_finalizer"]
    response = call_llm(messages, target_agent_nodes)
    print("SHOPPING_ADVISOR response: ", response)
    print("\n------------------------------------\n")
    # Check if the response indicates a search should be performed
    if response["should_search"] and "SEARCH:" in response["response"]:
        # Extract all search queries
        search_queries = [
            query.strip()
            for query in response["response"].split("SEARCH:")[1:]
            if query.strip()
        ]
        
        all_search_results = []
        for query in search_queries:
            # Get the clean query (remove any following text)
            clean_query = query.split("\n")[0].strip()
            search_results = find_clothing_items(clean_query)
            all_search_results.append({
                "query": clean_query,
                "results": search_results
            })
        
        # Add search results to messages and get new response
        messages.append({"role": "ai", "content": response["response"]})
        messages.append({
            "role": "system", 
            "content": f"Search results for all queries: {json.dumps(all_search_results)}"
        })
        response = call_llm(messages, target_agent_nodes)
        print("SHOPPING_ADVISOR response after search: ", response)
        print("\n------------------------------------\n")

    ai_msg = {"role": "ai", "content": response["response"], "name": "shopping_advisor"}
    return Command(goto=response["goto"], update={"messages": ai_msg})

def wardrobe_finalizer(
    state: MessagesState,
) -> Command[Literal["__end__"]]:
    system_prompt = (
        "You are a wardrobe finalizer that creates the final presentation by combining:"
        "1. The original outfit plan from the stylist_advisor"
        "2. The actual items found by the shopping_advisor"
        
        "Review the conversation history to identify:"
        "- The original outfit concept and search terms (in brackets)"
        "- The actual items found with their prices, links, and images"
        
        "IMPORTANT: Your response must ONLY contain a valid JSON object with no additional text or explanation. Use exactly this structure:"
        
        "{"
        "  'original_outfit_concept': {"
        "    'name': 'The outfit name',"
        "    'style_description': 'Style description from stylist_advisor'"
        "  },"
        "  'found_items': ["
        "    {"
        "      'original_search_term': 'what was requested',"
        "      'found_item': {"
        "        'name': 'actual item name',"
        "        'price': 'price in USD',"
        "        'link': 'product_link',"
        "        'image': 'product_image'"
        "      },"
        "      'match_analysis': 'Brief note on how well this matches the original request'"
        "    }"
        "  ],"
        "  'final_summary': {"
        "    'total_cost': 'total in USD',"
        "    'original_budget': 'budget in USD',"
        "    'budget_status': {"
        "      'status': 'under/over',"
        "      'difference': 'amount in USD'"
        "    },"
        "    'styling_instructions': 'How to wear these specific items together',"
        "    'care_instructions': 'Specific to the actual items found'"
        "  },"
        "  'shopping_recommendations': {"
        "    'priority_pieces': ['list of items to prioritize'],"
        "    'potential_savings': ['areas where savings could be found'],"
        "    'alternative_options': ['recommended alternatives if needed']"
        "  }"
        "}"
        
        "Do not include any other text, explanations, or formatting - only output the JSON object."
    )
    
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    target_agent_nodes = ["__end__"]
    response = call_llm(messages, target_agent_nodes)
    print("WARDROBE_FINALIZER response: ", response)
    print("\n------------------------------------\n")
    
    ai_msg = {"role": "ai", "content": response["response"], "name": "wardrobe_finalizer"}
    return Command(goto=response["goto"], update={"messages": ai_msg})



def run_stylist_service(query: str):
    # Update the graph builder to include the new agent
    builder = StateGraph(MessagesState)
    builder.add_node("stylist_advisor", stylist_advisor)
    builder.add_node("shopping_advisor", shopping_advisor)
    builder.add_node("wardrobe_finalizer", wardrobe_finalizer)

    # Update the edges to include the new flow
    builder.add_edge(START, "stylist_advisor")
    builder.add_edge("stylist_advisor", "shopping_advisor")
    builder.add_edge("shopping_advisor", "wardrobe_finalizer")
    builder.add_edge("wardrobe_finalizer", END)

    graph = builder.compile()
    result = graph.invoke({"messages": [("user", query)]})

    final_message = result["messages"][-1]
    print(final_message)
    print("\n------------------------------------\n")
    print(result["messages"])
    return final_message
