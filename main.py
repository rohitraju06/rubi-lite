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

def classify_intent(text: str) -> str:
    """
    Ask Phi to classify intent.
    Returns one of: query, save_note, save_link, upload_file, retrieve
    """
    instr = (
        "You are an intent classifier. "
        "Given a user message, reply with exactly one of: "
        "[query, save_note, save_link, upload_file, retrieve].\n\n"
        f"Message: {text}\nIntent:"
    )
    return query_ollama(instr)

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

    # 1) classify
    intent = classify_intent(text).lower()
    print(f"Classified intent: {intent}")

    # 2) route
    if intent == "query":
        # simple query -> LLM
        resp = query_ollama(text, list(conversation_memory))
        return {"response": resp}

    elif intent == "save_note":
        # inline note queuing without authentication
        queue = load_queue()
        queue.append({
            "type": "note",
            "text": text,
            "user": None,
            "timestamp": datetime.utcnow().isoformat()
        })
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}

    elif intent == "save_link":
        # inline link queuing without authentication
        queue = load_queue()
        queue.append({
            "type": "link",
            "url": text,
            "user": None,
            "timestamp": datetime.utcnow().isoformat()
        })
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}

    elif intent == "retrieve":
        # call your RAG service
        try:
            rag_resp = requests.post(RAG_URL, json={"prompt": text}, timeout=10)
            rag_resp.raise_for_status()
            data = rag_resp.json()
            return {"response": data.get("results", [])}
        except Exception as e:
            print("Error querying RAG:", e)
            return JSONResponse(status_code=500, content={"error": "RAG lookup failed"})

    else:
        # fallback to LLM
        resp = query_ollama(text, list(conversation_memory))
        return {"response": resp}


@app.post("/note")
async def add_note(item: NoteItem, user: dict = Depends(require_user)):
    if not item.text.strip():
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
async def add_link(item: LinkItem, user: dict = Depends(require_user)):
    if not item.url.strip():
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
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(require_user)
):
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