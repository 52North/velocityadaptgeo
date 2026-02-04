import tempfile
import logging
import sys
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
import asyncio
from typing import AsyncGenerator
from src.llm.main_agent import supervisor_app

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import logging
import sys

from src.llm.tools.navigation import get_route_to_room, extract_room_from_text

from pydantic import BaseModel
from typing import Optional, Dict, Any

from .voice2query import transcribe_audio_bytes, edit_query_with_name
from openai import OpenAI


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
app = FastAPI()
client = OpenAI()
graph = supervisor_app

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Get base path
BASE_DIR = Path(__file__).resolve().parent.parent

# Mount static files for frontend
app.mount("/static", StaticFiles(directory=str(BASE_DIR /
          "src" / "frontend")), name="static")

# Mount floorplans directory
app.mount("/floorplans", StaticFiles(directory=str(BASE_DIR /
          "floorplans")), name="floorplans")


class AskRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    state: Optional[Dict[str, Any]] = None


@app.get("/")
async def root():
    """Serve the frontend HTML"""
    return FileResponse(str(BASE_DIR / "src" / "frontend" / "index.html"))


@app.get("/api/health")
def health_check():
    """Health check endpoint"""
    return {"status": "ok", "message": "Server is running"}


async def stream_graph_state() -> AsyncGenerator[str, None]:
    """
    Async generator that streams LangGraph state continuously.
    """
    while True:
        # Fetch current state of the graph
        state = graph.get_state()  # Replace with actual method to get state
        # Send state as a JSON string
        yield f"data: {state}\n\n"
        await asyncio.sleep(1)  # Adjust the interval as needed


@app.get("/api/stream-graph-state")
async def stream_graph_state_endpoint():
    """
    SSE endpoint to stream LangGraph state to frontend.
    """
    return StreamingResponse(
        stream_graph_state(),
        media_type="text/event-stream"
    )


@app.post("/api/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest):
    """
    Standard synchronous ask endpoint using LangGraph invoke.
    """
    try:
        logger.info("Received /api/ask request")

        # Initial graph state
        initial_state = {
            "user_input": request.prompt,
        }

        # Invoke the compiled LangGraph app
        final_state = await supervisor_app.ainvoke(
            initial_state,
            config={
                "thread_id": request.session_id
            } if request.session_id else None
        )

        # Extract final answer (adjust key if needed)
        answer = (
            final_state.get("final_answer")
            or final_state.get("output")
            or "No answer produced."
        )

        return AskResponse(
            answer=answer,
            state=final_state
        )

    except Exception as e:
        logger.exception("Error during /api/ask")
        return AskResponse(
            answer="An internal error occurred.",
            state=None
        )

# API endpoint to get navigation route to a specific room


@app.get("/api/route/{room_id}")
async def get_navigation_route(room_id: str):
    """
    Get navigation route to a specific room.
    Returns path coordinates for drawing on the floor plan.
    """
    logger.info(f"Navigation request for room: {room_id}")

    route = get_route_to_room(room_id)

    if route is None:
        return JSONResponse(
            content={"error": f"No route found for room {room_id}",
                     "navigable": False},
            status_code=404
        )

    return JSONResponse(content={
        "navigable": True,
        "route": route
    })

# API endpoint to check navigation in text


@app.get("/api/check-navigation")
async def check_navigation(text: str):
    """
    Check if text contains a navigable room and return route if found.
    Used by frontend to automatically show navigation for room queries.
    """
    room_id = extract_room_from_text(text)

    if room_id is None:
        return JSONResponse(content={
            "found": False,
            "room_id": None,
            "route": None
        })

    route = get_route_to_room(room_id)

    return JSONResponse(content={
        "found": True,
        "room_id": room_id,
        "route": route
    })

# API endpoint for voice to query conversion


@app.post("/voice_to_query")
async def voice_to_query(file: UploadFile = File(...)):
    """API endpoint to handle voice to query conversion."""
    audio_bytes = await file.read()

    if not audio_bytes or len(audio_bytes) < 1000:
        return {"error": "empty/too small audio upload", "size": len(audio_bytes)}

    # wichtig: filename weitergeben, damit OpenAI das Format erkennt
    result = transcribe_audio_bytes(
        audio_bytes, filename=file.filename or "audio.webm")

    # result sollte ein dict sein: {"text": "...", "name": "..."}
    # du kannst debug infos zusätzlich zurückgeben:
    result["content_type"] = file.content_type
    result["size"] = len(audio_bytes)

    return result


class QueryIn(BaseModel):
    text: str


@app.post("/text_to_query")
async def text_to_query(payload: QueryIn):
    return edit_query_with_name(payload.text)
