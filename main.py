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

# --- Classification for high‑level actions ---
ALLOWED_ACTIONS = {"query", "store", "retrieve", "list", "delete"}

def classify_action(text: str) -> str:
    """
    Ask Phi for a single keyword action (query, store, retrieve, list, delete).
    Retries up to 3 times until one of ALLOWED_ACTIONS is returned.
    """
    prompt = (
        f"You are a classifier. Choose exactly one word from {sorted(ALLOWED_ACTIONS)} "
        f"that best matches the user's intent for the message:\n{text}\n"
        "Output only the single action:"
    )
    for _ in range(3):
        raw = query_ollama(prompt)
        action = raw.strip().lower()
        if action in ALLOWED_ACTIONS:
            return action
    # fallback
    return "query"

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

# --- Helper to find pending action ---
def find_pending_action():
    for msg in conversation_memory:
        if "pending_action" in msg:
            return msg["pending_action"], msg
    return None, None

# --- Endpoints ---
@app.post("/message")
async def handle_message(msg: MessagePayload):
    def parse_confirmation(text: str) -> bool:
        return text.strip().lower() in ("yes", "y", "ok", "okay")

    text = msg.text.strip()
    if not text:
        return JSONResponse(status_code=400, content={"error": "Empty message"})

    conversation_memory.append({"role": "user", "text": text})

    if parse_confirmation(text):
        action_name, pending_msg = find_pending_action()
        if action_name == "store":
            summary = pending_msg["text"]
            queue = load_queue()
            queue.append({
                "type": "note",
                "text": summary,
                "user": None,
                "timestamp": datetime.utcnow().isoformat()
            })
            save_queue(queue)
            # clear pending_action flags
            for msg in conversation_memory:
                msg.pop("pending_action", None)
            return {"status": "saved", "text": summary}
        elif action_name == "retrieve":
            # no confirmation needed for retrieve, simply clear and return
            _, pending_msg = find_pending_action()
            # clear flags
            for msg in conversation_memory:
                msg.pop("pending_action", None)
            # perform the original retrieval
            try:
                rag_resp = requests.post(RAG_URL, json={"prompt": pending_msg["text"]}, timeout=10)
                rag_resp.raise_for_status()
                results = rag_resp.json().get("results", [])
                return {"results": results}
            except Exception as e:
                print("Error querying RAG:", e)
                return JSONResponse(status_code=500, content={"error": "RAG lookup failed"})

    # 1) classify high‑level action
    action = classify_action(text)
    print(f"Classified action: {action}")

    # 3) route by action
    if action == "query":
        # limit response to two lines
        resp = query_ollama(f"{text}\nPlease answer in at most two lines.")
        conversation_memory.append({"role": "assistant", "text": resp})
        return {"response": resp}

    elif action == "store":
        # ask LLM to produce a concise summary line for saving
        summary = query_ollama(
            f"Summarize this personal memory or preference for storing:\n{text}"
        )
        # mark it as pending
        conversation_memory.append({"role": "assistant", "text": summary, "pending_action": "store"})
        return {"confirm": summary}

    elif action == "retrieve":
        # mark retrieve as pending so we can confirm or directly fetch
        phrased_query = query_ollama(
            f"Please phrase the query to best retrieve stored memories or notes related to this:\n{text}"
        )
        conversation_memory.append({"role": "assistant", "text": phrased_query, "pending_action": "retrieve"})
        return {"confirm_retrieve": "Do you want me to fetch results now?"}

    elif action == "list":
        data = load_queue()
        filtered = [item for item in data if item["type"] == intent_payload.type]  # reuse type from old classification?
        return {"items": filtered}

    elif action == "delete":
        data = load_queue()
        key = text.strip()
        new_data = [item for idx, item in enumerate(data) if str(idx) != key]
        save_queue(new_data)
        return {"status": "deleted", "remaining": len(new_data)}

    else:
        # fallback to full LLM response
        resp = query_ollama(text)
        conversation_memory.append({"role": "assistant", "text": resp})
        return {"response": resp}


@app.post("/note")
async def add_note(item: NoteItem, user: dict = Depends(require_user)):
    if not item or not item.text.strip():
        return JSONResponse(status_code=400, content={"error": "Empty note"})
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
    if not item or not item.url.strip():
        return JSONResponse(status_code=400, content={"error": "Empty URL"})
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
async def upload_file(file: UploadFile = File(...), user: dict = Depends(require_user)):
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