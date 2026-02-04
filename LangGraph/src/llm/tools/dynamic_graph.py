# src/llm/tools/graph_lg.py
import datetime
from langgraph.graph import StateGraph, START, END
from langchain_neo4j import Neo4jGraph, GraphCypherQAChain
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from dotenv import load_dotenv
import os
import logging

from src.llm.state.agent_state import AgentState

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Neo4j connection variables
NEO4J_HOST = os.getenv("NEO4J_HOST_LOCAL", "neo4j")
NEO4J_PORT = os.getenv("NEO4J_PORT_LOCAL", "7687")
NEO4J_URI = os.getenv("NEO4J_URI_LOCAL", f"bolt://{NEO4J_HOST}:{NEO4J_PORT}")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE_LOCAL", "neo4j")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME_LOCAL", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD_LOCAL", "")

from datetime import datetime
import neo4j.time

def neo4j_to_python_datetime(obj):
    """
    Recursively convert Neo4j DateTime objects to Python datetime.
    """
    if isinstance(obj, dict):
        return {k: neo4j_to_python_datetime(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [neo4j_to_python_datetime(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(neo4j_to_python_datetime(v) for v in obj)
    elif isinstance(obj, neo4j.time.DateTime):
        # Convert to Python datetime
        return datetime(
            obj.year, obj.month, obj.day,
            obj.hour, obj.minute, obj.second,
            obj.nanosecond // 1000,  # microseconds
            tzinfo=obj.tzinfo
        )
    else:
        return obj


class DynamicGraph:
    @staticmethod
    def get_graph_cypher_qa():
        graph = Neo4jGraph(
            url=NEO4J_URI,
            username=NEO4J_USERNAME,
            password=NEO4J_PASSWORD,
            database=NEO4J_DATABASE,
        )


        QA_TEMPLATE = """You are an assistant helping users find information about events in rooms in a building.
        Your main task is to answer when a room is occupied at a certain timeslot. 
        
        If you can find the room, but do not get a time occupied for this for the respective team, this means that the room is available.
        
        Question: {question}
        
        Database Results (Context):
        {context}
        
        Answer the question based on the context above.
        Be specific and include all room numbers found.
        If no information is found, say "I couldn't find any information about that."
        
        Answer:"""

        QA_PROMPT = PromptTemplate(input_variables=["context", "question"], template=QA_TEMPLATE)

        qa_chain = GraphCypherQAChain.from_llm(
            ChatOpenAI(temperature=0, model="gpt-4o-mini"),
            graph=graph,
            verbose=True,
            allow_dangerous_requests=True,
            #return_intermediate_steps=True, #Removed, due to parsing errors of NEO4J-Datetime type
            qa_prompt=QA_PROMPT,
            return_direct=False,

        )

        return qa_chain

    @staticmethod
    def node(state: AgentState):
        request = state["user_input"]  # TODO: Adjust if needed for prompt input variables

        qa_chain = DynamicGraph.get_graph_cypher_qa()
        result = qa_chain.invoke(request)

        state["dynamic_graph_result"] = result

        #safe_state = neo4j_to_python_datetime(result)
        #try:
        #    state["dynamic_json_result"] = safe_state["intermediate_steps"][1]["context"][0]
        #except (IndexError, KeyError, TypeError) as e:
        #    logger.warning(f"Could not extract JSON result from intermediate steps: {e}")
        #    state["dynamic_json_result"] = "Empty Response"


        return state


if __name__ == "__main__":
    import pprint
    logging.basicConfig(level=logging.INFO)

    # Minimal test state
    test_state: AgentState = {
        "user_input": "Is room GEO1 242 on the 10th of February 2026 occupied at 19:00?"
    }
    # TODO: Known Issues: GEO1 242 has to be in all-capital letters and exact match.
    # TODO: If query fails, we will get back an index out of range
    # TODO: Timestamp issues: 10.2.2026 -> datetime('2026-10-02T19:00:00') = 8 months after
    print("🧪 Running graph_node in debug mode...\n")

    updated_state = DynamicGraph.node(test_state)

    print("✅ Final state:")
    pprint.pprint(updated_state)
