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
from stylist_service import run_stylist_service

memory = {'test123': ''}
original_prompt = ""
model = ChatOpenAI(model="gpt-4o", max_retries=1)

load_dotenv()

def triage_agent(user_data: dict):
    """
    Generates a prompt for the 'search_agent' to use during the search phase based on the user's initial prompt.
    :param user_query: The user's initial prompt.
    :return: A prompt for the 'search_agent' to use during the search phase.
    """
    print("RESEARCH_AGENT")

    original_prompt = user_data['user_prompt']

    prompt = [{
        "role": "system",
        "content": f"As a helpful fashion asistant, your role is to chat with the user and collect information that will help our professional Stylist better serve our user. You need to collect the following information: \n"
                   f"- User gender\n"
                   f"- User style\n"
                   f"- User favorite brands\n"
                   f"Once the user provided ALL of the required information listed above, you should thank the user and add a [STOP] at the end of your response. Only add a [STOP] at the end of your response when you have ALL of the required information.\n"
                   f"Please try to keep your responses brief and do not reiterate the information the user provided.\n"
    }, {
        "role": "user",
        "content":  f"User prompt: {user_data['user_prompt']}"
                    f"Chat history: {memory['test123']}"
    }]

    converted = convert_openai_messages(prompt)
    response = model.invoke(converted).content

    memory['test123'] += f"User: {user_data['user_prompt']}\nAiResponse: {response}\n"

    return {"response": response, "user_message": user_data['user_prompt']}

def decision_agent(state: dict):
    print(state['response'])

    if ("[STOP]" in state['response']):
        print("DONE!")
        prompt = [{
            "role": "system",
            "content": f"Your only job is to accurately extract the following information about the user: \n"
                    f"- User gender\n"
                    f"- User style\n"
                    f"- User favorite brands\n"
                    f"Your response should be in JSON and be in the following format: \n"
                    f"{{\n"
                    f'    "user_gender": "<the gender of the user>",\n'
                    f'    "user_brands": "<an array with the user preferred brands>",\n'
                    f'    "user_style": "<the style the user wants>"\n'
                    f"}}\n"
                    f'Do not include any other text or formatting in your response. It should only be the JSON string response. Do not wrap the json codes in JSON markers. \n'
        }, {
            "role": "user",
            "content":  f"User prompt: {state['response']}"
                        f"Chat history: {memory['test123']}"
        }]

        converted = convert_openai_messages(prompt)
        response = model.invoke(converted).content

        parsed = json.loads(response)
        parsed['user_prompt'] = original_prompt
        parsed['is_done'] = True

        stylist_result = run_stylist_service(parsed)
        test = json.loads(stylist_result)
        return {"response": test, "is_done": True}
    else:
        print("KEEP GOING...")
        return {"response": state['response'], "is_done": False}

def formatter_agent(state: dict):
    print(state['response'])

def run_test_service(prompt: str):
    workflow = Graph()

    workflow.add_node("triage_agent", triage_agent)
    workflow.add_node("decision_agent", decision_agent)

    workflow.add_edge(START, "triage_agent")
    workflow.add_edge("triage_agent", "decision_agent")
    workflow.add_edge("decision_agent", END)

    chain = workflow.compile()

    result = chain.invoke(prompt)
    return json.dumps(result)