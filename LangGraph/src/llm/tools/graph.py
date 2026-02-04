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
NEO4J_HOST = os.getenv("NEO4J_HOST", "neo4j")
NEO4J_PORT = os.getenv("NEO4J_PORT", "7687")
NEO4J_URI = os.getenv("NEO4J_URI", f"bolt://{NEO4J_HOST}:{NEO4J_PORT}")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


class StaticGraph:
    @staticmethod
    def get_graph_cypher_qa():
        graph = Neo4jGraph(
            url=NEO4J_URI,
            username=NEO4J_USERNAME,
            password=NEO4J_PASSWORD,
            database=NEO4J_DATABASE,
        )

        # Ensure schema is available to the chain (important!)
        try:
            graph.refresh_schema()
        except Exception as e:
            logger.warning(f"Could not refresh Neo4j schema: {e}")

        CYPHER_TEMPLATE = """You are a Neo4j Cypher expert.
            Generate a single Cypher query that answers the user's question.

            Use ONLY the provided schema. Relationship direction matters.
            Never invent relationship types or directions under any circumstances. NEVER!

            SCHEMA:
            {schema}

            CRITICAL RELATIONSHIP RULES (direction matters):
            - A person has an office room like this:
            (:Person)-[:HAS_OFFICE]->(:Room)
            - A floor contains rooms like this:
            (:Floor)-[:HAS_ROOM]->(:Room)

            Therefore:
            - If the user asks for the floor of a person (or the floor of a room):
            MUST traverse: (p:Person)-[:HAS_OFFICE]->(r:Room)<-[:HAS_ROOM]-(f:Floor)
            - NEVER use: (r:Room)-[:HAS_ROOM]->(f:Floor)  (this direction does not exist)

            When the user asks for room number or floor:
            - Do NOT join to Institute unless explicitly asked.

            FEW-SHOT EXAMPLES:

            User: Which floor is Benjamin Risse on?
            Cypher:
            MATCH (p:Person {{name:"Benjamin Risse"}})-[:HAS_OFFICE]->(r:Room)<-[:HAS_ROOM]-(f:Floor)
            RETURN f

            User: On which floor is the office of Angela Schwering?
            Cypher:
            MATCH (p:Person {{name:"Angela Schwering"}})-[:HAS_OFFICE]->(r:Room)<-[:HAS_ROOM]-(f:Floor)
            RETURN f.number

            User: What room and floor does Benjamin Risse have?
            Cypher:
            MATCH (p:Person {{name:"Benjamin Risse"}})-[:HAS_OFFICE]->(r:Room)<-[:HAS_ROOM]-(f:Floor)
            RETURN r.number, f.number

            Now generate the Cypher query.

            User question:
            {question}

            Return ONLY the Cypher query (no markdown, no explanations).
            """

        CYPHER_PROMPT = PromptTemplate(
            input_variables=["schema", "question"],
            template=CYPHER_TEMPLATE,
        )

        QA_TEMPLATE = """You are an assistant helping users find information about rooms and people in a building.
        Based on the database query results below, provide a clear and complete answer.

        IMPORTANT: Always include specific room numbers when they are present in the context.
        - If r.number or room number is in the context, include it in your answer
        - Format room numbers clearly (e.g., "room 131", "room 241")
        - Include all relevant details like function, institute name, etc.
        - If a floor is asked for, a number is also fine as the name does not mean anything. Ignore the name, if it's a floor.
        
        Question: {question}

        Database Results (Context):
        {context}

        Answer the question based on the context above. Be specific and include all room numbers found.
        If no information is found, say "I couldn't find any information about that."

        Answer:"""

        QA_PROMPT = PromptTemplate(
            input_variables=["context", "question"],
            template=QA_TEMPLATE
        )

        qa_chain = GraphCypherQAChain.from_llm(
            llm=ChatOpenAI(temperature=0, model="gpt-4o-mini"),
            graph=graph,
            verbose=True,
            allow_dangerous_requests=True,
            return_intermediate_steps=True,
            return_direct=False,
            qa_prompt=QA_PROMPT,
            cypher_prompt=CYPHER_PROMPT,
        )

        return qa_chain

    @staticmethod
    def node(state: AgentState):
        request = state["user_input"]

        qa_chain = StaticGraph.get_graph_cypher_qa()
        result = qa_chain.invoke(request)

        print("#### Static Graph ####", result)
        state["static_graph_result"] = result
        try:
            state["static_json_result"] = result["intermediate_steps"][1]["context"][0]
        except (IndexError, KeyError, TypeError) as e:
            logger.warning(
                f"Could not extract JSON result from intermediate steps: {e}")
            state["static_json_result"] = "Empty Response"

        return state
