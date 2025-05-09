# main.py

import os
import json
from pathlib import Path
from datetime import datetime

import requests
from dotenv import load_dotenv

from fastapi import FastAPI, Request, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Annotated, Optional, List, Any

from auth import router as auth_router, require_user

from collections import deque

# keep last 20 messages for context
conversation_memory = deque(maxlen=20)

load_dotenv()

# --- Configuration ---
QUEUE_FILE = Path("queue.json")
DATA_FOLDER = Path("data")
DATA_FOLDER.mkdir(exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_API", "http://localhost:11434")
RAG_URL    = os.getenv("RAG_API",   "http://localhost:8000/query")  # your RAG pod endpoint

# --- Intent Schema ---
class IntentPayload(BaseModel):
    intent: str
    text:    Optional[str] = None
    url:     Optional[str] = None
    query:   Optional[str] = None
    type:    Optional[str] = None
    item_id: Optional[str] = None

# --- Helper functions ---
def load_queue():
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return []

def save_queue(queue):
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))

def query_ollama(prompt: str, history: list[dict] = None) -> str:
    """Call Phi to get a raw text response."""
    try:
        # build history string
        history_str = ""
        if history:
            for msg in history:
                role = "User" if msg["role"] == "user" else "Assistant"
                history_str += f"{role}: {msg['text']}\n"
        full_prompt = f"{history_str}User: {prompt}\nAssistant:"
        payload = {"model": "phi", "prompt": full_prompt, "stream": False}
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        response = data.get("response", "").strip() or "[no response]"
        conversation_memory.append({"role": "assistant", "text": response})
        return response
    except Exception as e:
        print("Error querying Ollama:", e)
        return "[Error querying LLM]"

def classify_intent(text: str) -> Optional[IntentPayload]:
    """
    Ask Phi to return a single-line JSON with fields:
      intent (one of [query, save_note, save_link, upload_file, retrieve, list, delete])
      plus the relevant argument field (text, url, query, type, or item_id).
    """
    prompt = (
        "You are an API router. For each user message, output exactly one line of JSON with:\n"
        "- intent: one of [query, save_note, save_link, upload_file, retrieve, list, delete]\n"
        "- the corresponding argument field:\n"
        "  * save_note  → text\n"
        "  * save_link  → url\n"
        "  * upload_file→ (no extra field)\n"
        "  * retrieve   → query\n"
        "  * list       → type (notes, links, uploads)\n"
        "  * delete     → item_id or query\n"
        "Examples:\n"
        "User: Save note my cat loves tuna\n"
        "{\"intent\":\"save_note\",\"text\":\"my cat loves tuna\"}\n"
        "User: Bookmark https://example.com\n"
        "{\"intent\":\"save_link\",\"url\":\"https://example.com\"}\n"
        "User: Show all notes\n"
        "{\"intent\":\"list\",\"type\":\"notes\"}\n"
        "User: Delete note 3\n"
        "{\"intent\":\"delete\",\"item_id\":\"3\"}\n"
        f"User: {text}\nOutput JSON:"
    )
    raw = query_ollama(prompt, list(conversation_memory))
    try:
        return IntentPayload.parse_raw(raw)
    except Exception as e:
        print("Failed to parse intent JSON:", raw, e)
        return None

# --- FastAPI setup ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)

# --- Data models ---
class MessagePayload(BaseModel):
    text: str

class NoteItem(BaseModel):
    text: str
    user: str = None

class LinkItem(BaseModel):
    url: str
    user: str = None

# --- Endpoints ---
@app.post("/message")
async def handle_message(msg: MessagePayload):
    text = msg.text.strip()
    if not text:
        return JSONResponse(400, {"error": "Empty message"})

    conversation_memory.append({"role": "user", "text": text})

    # 1) classify with structured JSON
    intent_payload = classify_intent(text)
    if not intent_payload:
        # fallback to simple query
        resp = query_ollama(text, list(conversation_memory))
        return {"response": resp}

    intent = intent_payload.intent
    args   = intent_payload.dict()
    print(f"Intent payload: {args}")

    # 2) route by intent
    if intent == "query":
        resp = query_ollama(text, list(conversation_memory))
        return {"response": resp}

    elif intent == "save_note":
        queue = load_queue()
        queue.append({
            "type": "note",
            "text": intent_payload.text,
            "user": None,
            "timestamp": datetime.utcnow().isoformat()
        })
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}

    elif intent == "save_link":
        queue = load_queue()
        queue.append({
            "type": "link",
            "url": intent_payload.url,
            "user": None,
            "timestamp": datetime.utcnow().isoformat()
        })
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}

    elif intent == "retrieve":
        try:
            rag_resp = requests.post(RAG_URL, json={"prompt": intent_payload.query}, timeout=10)
            rag_resp.raise_for_status()
            results = rag_resp.json().get("results", [])
            return {"response": results}
        except Exception as e:
            print("Error querying RAG:", e)
            return JSONResponse(status_code=500, content={"error": "RAG lookup failed"})

    elif intent == "list":
        data = load_queue()
        filtered = [item for item in data if item["type"] == intent_payload.type]
        return {"items": filtered}

    elif intent == "delete":
        data = load_queue()
        key = intent_payload.item_id or intent_payload.query
        new_data = [item for idx,item in enumerate(data) if str(idx) != key and (key.lower() not in json.dumps(item).lower())]
        save_queue(new_data)
        return {"status":"deleted", "remaining": len(new_data)}

    else:
        resp = query_ollama(text, list(conversation_memory))
        return {"response": resp}


@app.post("/note")
async def add_note(user: dict = Depends(require_user), item: NoteItem = None):
    if not item or not item.text.strip():
        return JSONResponse(400, {"error": "Empty note"})
    queue = load_queue()
    queue.append({
        "type": "note",
        "text": item.text,
        "user": user.get("user"),
        "timestamp": datetime.utcnow().isoformat()
    })
    save_queue(queue)
    return {"status": "queued", "id": len(queue)-1}


@app.post("/link")
async def add_link(user: dict = Depends(require_user), item: LinkItem = None):
    if not item or not item.url.strip():
        return JSONResponse(400, {"error": "Empty URL"})
    queue = load_queue()
    queue.append({
        "type": "link",
        "url": item.url,
        "user": user.get("user"),
        "timestamp": datetime.utcnow().isoformat()
    })
    save_queue(queue)
    return {"status": "queued", "id": len(queue)-1}


@app.post("/upload")
async def upload_file(user: dict = Depends(require_user), file: UploadFile = File(...)):
    contents = await file.read()
    dest = DATA_FOLDER / file.filename
    dest.write_bytes(contents)

    queue = load_queue()
    queue.append({
        "type": "upload",
        "filename": file.filename,
        "path": str(dest),
        "user": user.get("user"),
        "timestamp": datetime.utcnow().isoformat()
    })
    save_queue(queue)
    return {"status": "queued", "id": len(queue)-1}