from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from pathlib import Path
import json
from fastapi.responses import StreamingResponse
from src.llm.workflow import compiled_graph
from src.helper.helper import pretty_print_messages

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI()

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

class ChatRequest(BaseModel):
    prompt: str

class ChatResponse(BaseModel):
    response: str

@app.post("/api/chat", response_model=ChatResponse)
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

@app.get("/api/stream")
async def stream(prompt: str, thread_id: str):
    async def gen():
        input_state = {
            "messages": [HumanMessage(content=prompt)]
        }

        config = {"configurable": {"thread_id": thread_id}}

        async for path, (message_chunk, metadata) in compiled_graph.astream(
            input_state,
            config=config,
            stream_mode="messages",
            subgraphs=True
        ):
            content = message_chunk.content

            payload = {
                "path": path,
                "metadata": metadata,
                "type": message_chunk.type,
                "id": message_chunk.id,
            }

            # Stream artifact if present to render geometry on frontend map
            if getattr(message_chunk, "artifact", None):
                payload["artifact"] = message_chunk.artifact
                print("Streaming artifact:", message_chunk.artifact)

            # Normal textual streaming
            if isinstance(content, str):
                payload["content"] = content
                yield f"data: {json.dumps(payload)}\n\n"

            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        payload["content"] = block["text"]
                        yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")
