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

def find_clothing_items(query: str):
    """
    Find clothing items based on a query.
    """
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": os.getenv("SERPAPI_API_KEY"),
        "num": 5,
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

    print(formatted_results)

# def build_wardrobe(preferences: str, budget: str, season: str):
#     tools = [
#         Tool(name="Shopping",
#         func=find_clothing_items,
#         description="Find clothing items based on a query."
#         )
#     ]

#     search_planning_prompt = PromptTemplate(
#     input_variables=["preferences", "budget", "season"],)
  

#     llm = ChatOpenAI(temperature=0.7, model_name="gpt-3.5-turbo", api_key=os.getenv("OPENAI_API_KEY"))
#     # react_agent = initialize_agent(tools, llm, agent="zero-shot-react-description", verbose=True)

#     search_planning_chain = search_planning_prompt | llm
#     res = search_planning_chain.invoke({"preferences": preferences, "budget": budget, "season": season}, verbose=True)
#     print(res.pretty_print())
#     # react_agent.invoke(query)
#     # find_clothing_items(query)


# class WardrobePlannerState(TypedDict):

model = ChatOpenAI(model="gpt-3.5-turbo")

# Define a helper for each of the agent nodes to call
def call_llm(messages: list[AnyMessage], target_agent_nodes: list[str]):
    """Call LLM with structured output to get a natural language response as well as a target agent (node) to go to next.

    Args:
        messages: list of messages to pass to the LLM
        target_agents: list of the node names of the target agents to navigate to
    """
    # define JSON schema for the structured output:
    # - model's text response (`response`)
    # - name of the node to go to next (or 'finish')
    # see more on structured output here https://python.langchain.com/docs/concepts/structured_outputs
    json_schema = {
        "name": "Response",
        "parameters": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "A human readable response to the original question. Does not need to be a final response. Will be streamed back to the user.",
                },
                "goto": {
                    "enum": [*target_agent_nodes, "__end__"],
                    "type": "string",
                    "description": "The next agent to call, or __end__ if the user's query has been resolved. Must be one of the specified values.",
                },
            },
            "required": ["response", "goto"],
        },
    }
    response = model.with_structured_output(json_schema).invoke(messages)
    return response


def stylist_advisor(
    state: MessagesState,
) -> Command[Literal["fashion_advisor", "shopping_advisor", "__end__"]]:
    system_prompt = (
        "You are a personal stylist expert that can craft various different outfits inspirations based on the users style preferences. "
        "If you need specific clothing items recommendations, ask 'fashion_advisor' for help. "
        "If you need help finding clothing items online or want store website recommendations, ask 'shopping_advisor' for help. "
        "If you have enough information to respond to the user, return 'finish'. "
        "Never mention other agents by name."
    )
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    target_agent_nodes = ["fashion_advisor", "shopping_advisor"]
    response = call_llm(messages, target_agent_nodes)
    ai_msg = {"role": "ai", "content": response["response"], "name": "stylist_advisor"}
    # handoff to another agent or halt
    return Command(goto=response["goto"], update={"messages": ai_msg})


def fashion_advisor(
    state: MessagesState,
) -> Command[Literal["stylist_advisor", "shopping_advisor", "__end__"]]:
    system_prompt = (
        "You are a fashion expert that can provide specific outfit recommendations for a given style preference. "
        "If you need general outfit inspiration recommendations, go to 'stylist_advisor' for help. "
        "If you need help finding clothing items online or want store website recommendations, ask 'shopping_advisor' for help. "
        "If you have enough information to respond to the user, return 'finish'. "
        "Never mention other agents by name."
    )
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    target_agent_nodes = ["stylist_advisor", "shopping_advisor"]
    response = call_llm(messages, target_agent_nodes)
    ai_msg = {
        "role": "ai",
        "content": response["response"],
        "name": "fashion_advisor",
    }
    # handoff to another agent or halt
    return Command(goto=response["goto"], update={"messages": ai_msg})


def shopping_advisor(
    state: MessagesState,
) -> Command[Literal["stylist_advisor", "fashion_advisor", "__end__"]]:
    system_prompt = (
        "You are a shopping expert that can provide specific clothing items recommendations and store website recommendations."
        "If you need general outfit inspiration recommendations, go to 'stylist_advisor' for help. "
        "If you need specific clothing item recommendations, ask 'fashion_advisor' for help. "
        "If you have enough information to respond to the user, return 'finish'. "
        "Never mention other agents by name."
    )
    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    target_agent_nodes = ["stylist_advisor", "fashion_advisor"]
    response = call_llm(messages, target_agent_nodes)
    ai_msg = {"role": "ai", "content": response["response"], "name": "shopping_advisor"}
    # handoff to another agent or halt
    return Command(goto=response["goto"], update={"messages": ai_msg})


builder = StateGraph(MessagesState)
builder.add_node("stylist_advisor", stylist_advisor)
builder.add_node("fashion_advisor", fashion_advisor)
builder.add_node("shopping_advisor", shopping_advisor)
# we'll always start with a general travel advisor
builder.add_edge(START, "stylist_advisor")

graph = builder.compile()

for chunk in graph.stream(
    {
        "messages": [
            (
                "user",
                "I am looking for a new outfit for a casual dinner date. I like netural colors and prefer a casual style.",
            )
        ]
    }
):
    print(chunk)
    print("\n")

