from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage
from typing import TypedDict, Optional, Any

from langchain_classic.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage, AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
# from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI
import json

from src.llm.state.agent_state import AgentState
from src.llm.tools.graph import StaticGraph
from src.llm.tools.dynamic_graph import DynamicGraph
from dotenv import load_dotenv
import os

load_dotenv()

workflow = StateGraph()
