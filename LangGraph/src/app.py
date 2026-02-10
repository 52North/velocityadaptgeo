from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from pathlib import Path

from llm.workflow import compiled_graph
from helper.helper import pretty_print_messages

app = FastAPI()

class ChatRequest(BaseModel):
    prompt: str

class ChatResponse(BaseModel):
    response: str

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    input_state = {
        "messages": [HumanMessage(content=req.prompt)]
    }

    # Run LangGraph normally (no streaming for now)
    result = await compiled_graph.ainvoke(input_state)

    # Last message is the assistant reply
    assistant_message = result["messages"][-1].content

    pretty_print_messages(result["messages"])

    return ChatResponse(response=assistant_message)

@app.post("/api/stream_chat")
async def stream_chat(req: ChatRequest):
    input_state = {
        "messages": [HumanMessage(content=req.prompt)]
    }

    # Run LangGraph with streaming enabled
    async for result in compiled_graph.astream(input_state):
        assistant_message = result["messages"][-1].content
        print("Streaming assistant message:", assistant_message)  # Debug log
        yield assistant_message



BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")
