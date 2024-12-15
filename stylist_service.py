from langchain_community.llms import OpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_community.chat_models import ChatOpenAI
from langchain_community.agent_toolkits.load_tools import load_tools
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import MessagesState, START, StateGraph, END

import json
import os
import traceback

class StylistService:
    def __init__(self, api_key: str = None):
        """
        Initialize the StylistService with OpenAI API key and necessary components.
        
        Args:
            api_key (str, optional): OpenAI API key. If not provided, will try to use environment variable.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key must be provided or set in environment variables")
        
        # Initialize the language model
        self.llm = ChatOpenAI(
            temperature=0.7,
            model_name="gpt-3.5-turbo",
            api_key=self.api_key
        )
        self.search = DuckDuckGoSearchRun()

    def build_wardrobe(self, query: str):
        tools = [self.search]
        llm_with_tools = self.llm.bind_tools(tools)

        human_message = HumanMessage(content=query)
        system_message = SystemMessage(content= 
        """
        You are in charge of planning outfits for a person. You are a very skilled personal stylish with a lot of experience in the industry.

        Given the user's style preferences, create a series of outfit recommendations that fit their needs and style.
        """)

        def reasoner(state: MessagesState):
            return {"messages": [llm_with_tools.invoke([system_message] + state["messages"])]}


        builder = StateGraph(MessagesState)

        builder.add_node("reasoner", reasoner)
        builder.add_node("tools", ToolNode(tools))

        builder.add_edge(START, "reasoner")
        builder.add_conditional_edges(
            "reasoner",
            tools_condition,
        )
        builder.add_edge("tools", "reasoner")
        react_graph = builder.compile()

        display(Image(react_graph.get_graph(xray=True).draw_mermaid_png()))
        

    def search_clothing_item(self, query: str):
        try:
            search_query = f"{query} clothing price site"
            search_result = self.search.run(search_query)
            print("SEARCH RESULT: ", search_result)
            return search_result
        except Exception as e:
            print(f"Error searching for item: {str(e)}")
            return None